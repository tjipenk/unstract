import os
import time
from logging import Logger
from typing import Any, Optional

from dotenv import load_dotenv
from flask import current_app as app
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
from unstract.prompt_service.exceptions import APIError, RateLimitError
from unstract.prompt_service_v2.constants import (
    DBTableV2,
    ExecutionSource,
    FeatureFlag,
    FileStorageKeys,
)
from unstract.prompt_service_v2.constants import PromptServiceContants as PSKeys
from unstract.prompt_service_v2.constants import RunLevel
from unstract.prompt_service_v2.extensions import db
from unstract.prompt_service_v2.helper.plugin_helper import PluginManager
from unstract.prompt_service_v2.utils.db_utils import DBUtils
from unstract.prompt_service_v2.utils.env_loader import get_env_or_die
from unstract.prompt_service_v2.utils.log import publish_log
from unstract.sdk.constants import LogLevel
from unstract.sdk.exceptions import RateLimitError as SdkRateLimitError
from unstract.sdk.exceptions import SdkError
from unstract.sdk.index import Index
from unstract.sdk.llm import LLM

from unstract.flags.feature_flag import check_feature_flag_status

if check_feature_flag_status(FeatureFlag.REMOTE_FILE_STORAGE):
    from unstract.sdk.file_storage import FileStorage, FileStorageProvider
    from unstract.sdk.file_storage.constants import StorageType
    from unstract.sdk.file_storage.env_helper import EnvHelper

PAID_FEATURE_MSG = (
    "It is a cloud / enterprise feature. If you have purchased a plan and still "
    "face this issue, please contact support"
)
NO_CONTEXT_ERROR = (
    "Couldn't fetch context from vector DB. "
    "This happens usually due to a delay by the Vector DB "
    "provider to confirm writes to DB. "
    "Please try again after some time"
)

load_dotenv()


def get_cleaned_context(context: set[str]) -> list[str]:
    clean_context_plugin: dict[str, Any] = PluginManager().get_plugin(
        PSKeys.CLEAN_CONTEXT
    )
    if clean_context_plugin:
        return clean_context_plugin["entrypoint_cls"].run(context=context)
    return list(context)


def run_retrieval(  # type:ignore
    tool_settings: dict[str, Any],
    output: dict[str, Any],
    doc_id: str,
    llm: LLM,
    vector_index,
    retrieval_type: str,
    metadata: dict[str, Any],
    execution_source: Optional[str] = None,
) -> tuple[str, set[str]]:
    context: set[str] = set()
    prompt = output[PSKeys.PROMPTX]
    if retrieval_type == PSKeys.SUBQUESTION:
        subq_prompt: str = (
            f"I am sending you a verbose prompt \n \n Prompt : {prompt} \n \n"
            "Generate set of specific subquestions "
            "from the prompt which can be used to retrive "
            "relevant context from vector db. "
            "Use your logical abilities to "
            " only generate as many subquestions as necessary "
            " — fewer subquestions if the prompt is simpler. "
            "Decide the minimum limit for subquestions "
            "based on the complexity input prompt and set the maximum limit"
            "for the subquestions to 10."
            "Ensure that each subquestion is distinct and relevant"
            "to the the original query. "
            "Do not add subquestions for details"
            "not mentioned in the original prompt."
            " The goal is to maximize retrieval accuracy"
            " using these subquestions. Use your logical abilities to ensure "
            " that each subquestion targets a distinct aspect of the original query."
            " Please note that, there are cases where the "
            "response might have a list of answers. The subquestions must not miss out "
            "any values in these cases. "
            "Output should be a list of comma seperated "
            "subquestion prompts. Do not change this format. \n \n "
            " Subquestions : "
        )
        subquestions = run_completion(
            llm=llm,
            prompt=subq_prompt,
        )
        subquestion_list = subquestions.split(",")
        for each_subq in subquestion_list:
            retrieved_context = _retrieve_context(
                output, doc_id, vector_index, each_subq
            )
            context.update(retrieved_context)

    if retrieval_type == PSKeys.SIMPLE:

        context = _retrieve_context(output, doc_id, vector_index, prompt)

        if not context:
            # UN-1288 For Pinecone, we are seeing an inconsistent case where
            # query with doc_id fails even though indexing just happened.
            # This causes the following retrieve to return no text.
            # To rule out any lag on the Pinecone vector DB write,
            # the following sleep is added
            # Note: This will not fix the issue. Since this issue is inconsistent
            # and not reproducible easily, this is just a safety net.
            time.sleep(2)
            context = _retrieve_context(output, doc_id, vector_index, prompt)

    answer = construct_and_run_prompt(  # type:ignore
        tool_settings=tool_settings,
        output=output,
        llm=llm,
        context="\n".join(context),
        prompt="promptx",
        metadata=metadata,
        execution_source=execution_source,
    )

    return (answer, context)


def _retrieve_context(output, doc_id, vector_index, answer) -> set[str]:
    retriever = vector_index.as_retriever(
        similarity_top_k=output[PSKeys.SIMILARITY_TOP_K],
        filters=MetadataFilters(
            filters=[
                ExactMatchFilter(key="doc_id", value=doc_id),
                # TODO: Enable after adding section in GUI
                # ExactMatchFilter(
                #     key="section", value=output["section"]
            ],
        ),
    )
    nodes = retriever.retrieve(answer)
    context: set[str] = set()
    for node in nodes:
        # ToDo: May have to fine-tune this value for node score or keep it
        # configurable at the adapter level
        if node.score > 0:
            context.add(node.get_content())
        else:
            app.logger.info(
                "Node score is less than 0. "
                f"Ignored: {node.node_id} with score {node.score}"
            )
    return context


def fetch_context_from_vector_db(
    index: Index,
    output: dict[str, Any],
    doc_id: str,
    tool_id: str,
    doc_name: str,
    prompt_name: str,
    log_events_id: str,
    usage_kwargs: dict[str, Any],
) -> set[str]:
    """
    Fetches context from the index for the given document ID. Implements a retry
    mechanism with logging and raises an error if context retrieval fails.

    Args:
        index: The index object to query.
        output: Dictionary containing keys like embedding and vector DB instance ID.
        doc_id: The document ID to query.
        tool_id: Identifier for the tool in use.
        doc_name: Name of the document being queried.
        prompt_name: Name of the prompt being executed.
        log_events_id: Unique ID for logging events.
        usage_kwargs: Additional usage parameters.

    Raises:
        APIError: If context retrieval fails after retrying.
    """
    context: set[str] = set()
    try:
        retrieved_context = index.query_index(
            embedding_instance_id=output[PSKeys.EMBEDDING],
            vector_db_instance_id=output[PSKeys.VECTOR_DB],
            doc_id=doc_id,
            usage_kwargs=usage_kwargs,
        )

        if retrieved_context:
            context.add(retrieved_context)
            publish_log(
                log_events_id,
                {
                    "tool_id": tool_id,
                    "prompt_key": prompt_name,
                    "doc_name": doc_name,
                },
                LogLevel.DEBUG,
                RunLevel.RUN,
                "Fetched context from vector DB",
            )
        else:
            # Handle lag in vector DB write (e.g., Pinecone issue)
            time.sleep(2)
            retrieved_context = index.query_index(
                embedding_instance_id=output[PSKeys.EMBEDDING],
                vector_db_instance_id=output[PSKeys.VECTOR_DB],
                doc_id=doc_id,
                usage_kwargs=usage_kwargs,
            )

            if retrieved_context is None:
                msg = NO_CONTEXT_ERROR
                app.logger.error(
                    f"{msg} {output[PSKeys.VECTOR_DB]} for doc_id {doc_id}"
                )
                publish_log(
                    log_events_id,
                    {
                        "tool_id": tool_id,
                        "prompt_key": prompt_name,
                        "doc_name": doc_name,
                    },
                    LogLevel.ERROR,
                    RunLevel.RUN,
                    msg,
                )
                raise APIError(message=msg)
    except SdkError as e:
        msg = f"Unable to fetch context from vector DB. {str(e)}"
        app.logger.error(
            f"{msg}. VectorDB: {output[PSKeys.VECTOR_DB]}, doc_id: {doc_id}"
        )
        publish_log(
            log_events_id,
            {
                "tool_id": tool_id,
                "prompt_key": prompt_name,
                "doc_name": doc_name,
            },
            LogLevel.ERROR,
            RunLevel.RUN,
            msg,
        )
        raise APIError(message=msg, code=e.status_code)
    return context


def query_usage_metadata(token: str, metadata: dict[str, Any]) -> dict[str, Any]:
    DB_SCHEMA = get_env_or_die("DB_SCHEMA", "unstract")
    organization_uid, org_id = DBUtils.get_organization_from_bearer_token(token)
    run_id: str = metadata["run_id"]
    query: str = f"""
        SELECT
            usage_type,
            llm_usage_reason,
            model_name,
            SUM(prompt_tokens) AS input_tokens,
            SUM(completion_tokens) AS output_tokens,
            SUM(total_tokens) AS total_tokens,
            SUM(embedding_tokens) AS embedding_tokens,
            SUM(cost_in_dollars) AS cost_in_dollars
        FROM "{DB_SCHEMA}"."{DBTableV2.TOKEN_USAGE}"
        WHERE run_id = %s and organization_id = %s
        GROUP BY usage_type, llm_usage_reason, model_name;
    """
    logger: Logger = app.logger
    try:
        with db.atomic():
            logger.info(
                "Querying usage metadata for org_id: %s, run_id: %s", org_id, run_id
            )
            cursor = db.execute_sql(query, (run_id, organization_uid))
            results: list[tuple] = cursor.fetchall()
            # Process results as needed
            for row in results:
                key, item = _get_key_and_item(row)
                # Initialize the key as an empty list if it doesn't exist
                if key not in metadata:
                    metadata[key] = []
                # Append the item to the list associated with the key
                metadata[key].append(item)
    except Exception as e:
        logger.error(f"Error executing querying usage metadata: {e}")
    return metadata


def _get_key_and_item(row: tuple) -> tuple[str, dict[str, Any]]:
    (
        usage_type,
        llm_usage_reason,
        model_name,
        input_tokens,
        output_tokens,
        total_tokens,
        embedding_tokens,
        cost_in_dollars,
    ) = row
    cost_in_dollars: str = _format_float_positional(cost_in_dollars)
    key: str = usage_type
    item: dict[str, Any] = {
        "model_name": model_name,
        "cost_in_dollars": cost_in_dollars,
    }
    if llm_usage_reason:
        key = f"{llm_usage_reason}_{key}"
        item["input_tokens"] = input_tokens
        item["output_tokens"] = output_tokens
        item["total_tokens"] = total_tokens
    else:
        item["embedding_tokens"] = embedding_tokens
    return key, item


def _format_float_positional(value: float, precision: int = 10) -> str:
    formatted: str = f"{value:.{precision}f}"
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def extract_variable(
    structured_output: dict[str, Any],
    variable_names: list[Any],
    output: dict[str, Any],
    promptx: str,
) -> str:
    logger: Logger = app.logger
    for variable_name in variable_names:
        if promptx.find(f"%{variable_name}%") >= 0:
            if variable_name in structured_output:
                promptx = promptx.replace(
                    f"%{variable_name}%",
                    str(structured_output[variable_name]),
                )
            else:
                raise ValueError(
                    f"Variable {variable_name} not found " "in structured output"
                )

    if promptx != output[PSKeys.PROMPT]:
        logger.info(f"Prompt after variable replacement: {promptx}")
    return promptx


def construct_and_run_prompt(
    tool_settings: dict[str, Any],
    output: dict[str, Any],
    llm: LLM,
    context: str,
    prompt: str,
    metadata: dict[str, Any],
    file_path: str = "",
    execution_source: Optional[str] = ExecutionSource.IDE.value,
) -> str:
    platform_postamble = tool_settings.get(PSKeys.PLATFORM_POSTAMBLE, "")
    summarize_as_source = tool_settings.get(PSKeys.SUMMARIZE_AS_SOURCE)
    enable_highlight = tool_settings.get(PSKeys.ENABLE_HIGHLIGHT, False)
    if not enable_highlight or summarize_as_source:
        platform_postamble = ""
    prompt = construct_prompt(
        preamble=tool_settings.get(PSKeys.PREAMBLE, ""),
        prompt=output[prompt],
        postamble=tool_settings.get(PSKeys.POSTAMBLE, ""),
        grammar_list=tool_settings.get(PSKeys.GRAMMAR, []),
        context=context,
        platform_postamble=platform_postamble,
    )
    return run_completion(
        llm=llm,
        prompt=prompt,
        metadata=metadata,
        prompt_key=output[PSKeys.NAME],
        prompt_type=output.get(PSKeys.TYPE, PSKeys.TEXT),
        enable_highlight=enable_highlight,
        file_path=file_path,
        execution_source=execution_source,
    )


def construct_prompt(
    preamble: str,
    prompt: str,
    postamble: str,
    grammar_list: list[dict[str, Any]],
    context: str,
    platform_postamble: str,
) -> str:
    prompt = f"{preamble}\n\nQuestion or Instruction: {prompt}"
    if grammar_list is not None and len(grammar_list) > 0:
        prompt += "\n"
        for grammar in grammar_list:
            word = ""
            synonyms = []
            if PSKeys.WORD in grammar:
                word = grammar[PSKeys.WORD]
                if PSKeys.SYNONYMS in grammar:
                    synonyms = grammar[PSKeys.SYNONYMS]
            if len(synonyms) > 0 and word != "":
                prompt += f'\nNote: You can consider that the word {word} is same as \
                    {", ".join(synonyms)} in both the quesiton and the context.'  # noqa
    if platform_postamble:
        platform_postamble += "\n\n"
    prompt += (
        f"\n\n{postamble}\n\nContext:\n---------------\n{context}\n"
        f"-----------------\n\n{platform_postamble}Answer:"
    )
    return prompt


def run_completion(
    llm: LLM,
    prompt: str,
    metadata: Optional[dict[str, str]] = None,
    prompt_key: Optional[str] = None,
    prompt_type: Optional[str] = PSKeys.TEXT,
    enable_highlight: bool = False,
    file_path: str = "",
    execution_source: Optional[str] = None,
) -> str:
    logger: Logger = app.logger
    try:
        highlight_data_plugin: dict[str, Any] = PluginManager().get_plugin(
            PSKeys.HIGHLIGHT_DATA_PLUGIN
        )
        highlight_data = None
        if highlight_data_plugin and enable_highlight:
            if check_feature_flag_status(FeatureFlag.REMOTE_FILE_STORAGE):
                fs_instance: FileStorage = FileStorage(FileStorageProvider.LOCAL)
                if execution_source == ExecutionSource.IDE.value:
                    fs_instance = EnvHelper.get_storage(
                        storage_type=StorageType.PERMANENT,
                        env_name=FileStorageKeys.PERMANENT_REMOTE_STORAGE,
                    )
                if execution_source == ExecutionSource.TOOL.value:
                    fs_instance = EnvHelper.get_storage(
                        storage_type=StorageType.TEMPORARY,
                        env_name=FileStorageKeys.TEMPORARY_REMOTE_STORAGE,
                    )
                highlight_data = highlight_data_plugin["entrypoint_cls"](
                    logger=app.logger,
                    file_path=file_path,
                    fs_instance=fs_instance,
                ).run
            else:
                highlight_data = highlight_data_plugin["entrypoint_cls"](
                    logger=app.logger, file_path=file_path
                ).run
        completion = llm.complete(
            prompt=prompt,
            process_text=highlight_data,
            extract_json=prompt_type.lower() != PSKeys.TEXT,
        )
        answer: str = completion[PSKeys.RESPONSE].text
        highlight_data = completion.get(PSKeys.HIGHLIGHT_DATA, [])
        confidence_data = completion.get(PSKeys.CONFIDENCE_DATA)
        if metadata is not None and prompt_key:
            metadata.setdefault(PSKeys.HIGHLIGHT_DATA, {})[prompt_key] = highlight_data

            if confidence_data:
                metadata.setdefault(PSKeys.CONFIDENCE_DATA, {})[
                    prompt_key
                ] = confidence_data
        return answer
    # TODO: Catch and handle specific exception here
    except SdkRateLimitError as e:
        raise RateLimitError(f"Rate limit error. {str(e)}") from e
    except SdkError as e:
        logger.error(f"Error fetching response for prompt: {e}.")
        # TODO: Publish this error as a FE update
        raise APIError(str(e)) from e


def extract_table(
    output: dict[str, Any],
    structured_output: dict[str, Any],
    llm: LLM,
    enforce_type: str,
    execution_source: str,
) -> dict[str, Any]:
    table_settings = output[PSKeys.TABLE_SETTINGS]
    table_extractor: dict[str, Any] = PluginManager().get_plugin("table-extractor")
    if not table_extractor:
        raise APIError(
            "Unable to extract table details. "
            "Please contact admin to resolve this issue."
        )
    if check_feature_flag_status(FeatureFlag.REMOTE_FILE_STORAGE):
        fs_instance: FileStorage = FileStorage(FileStorageProvider.LOCAL)
        if execution_source == ExecutionSource.IDE.value:
            fs_instance = EnvHelper.get_storage(
                storage_type=StorageType.PERMANENT,
                env_name=FileStorageKeys.PERMANENT_REMOTE_STORAGE,
            )
        if execution_source == ExecutionSource.TOOL.value:
            fs_instance = EnvHelper.get_storage(
                storage_type=StorageType.TEMPORARY,
                env_name=FileStorageKeys.TEMPORARY_REMOTE_STORAGE,
            )
    try:
        if check_feature_flag_status(FeatureFlag.REMOTE_FILE_STORAGE):
            answer = table_extractor["entrypoint_cls"].extract_large_table(
                llm=llm,
                table_settings=table_settings,
                enforce_type=enforce_type,
                fs_instance=fs_instance,
            )
        else:
            answer = table_extractor["entrypoint_cls"].extract_large_table(
                llm=llm,
                table_settings=table_settings,
                enforce_type=enforce_type,
            )
        structured_output[output[PSKeys.NAME]] = answer
        # We do not support summary and eval for table.
        # Hence returning the result
        return structured_output
    except table_extractor["exception_cls"] as e:
        msg = f"Couldn't extract table. {e}"
        raise APIError(message=msg)


def extract_line_item(
    tool_settings: dict[str, Any],
    output: dict[str, Any],
    structured_output: dict[str, Any],
    llm: LLM,
    file_path: str,
    metadata: Optional[dict[str, str]],
    execution_source: str,
) -> dict[str, Any]:
    line_item_extraction_plugin: dict[str, Any] = PluginManager().get_plugin(
        "line-item-extraction"
    )
    if not line_item_extraction_plugin:
        raise APIError(PAID_FEATURE_MSG)

    extract_file_path = file_path
    if execution_source == ExecutionSource.IDE.value:
        # Adjust file path to read from the extract folder
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        extract_file_path = os.path.join(
            os.path.dirname(file_path), "extract", f"{base_name}.txt"
        )

    # Read file content into context
    if check_feature_flag_status(FeatureFlag.REMOTE_FILE_STORAGE):
        fs_instance: FileStorage = FileStorage(FileStorageProvider.LOCAL)
        if execution_source == ExecutionSource.IDE.value:
            fs_instance = EnvHelper.get_storage(
                storage_type=StorageType.PERMANENT,
                env_name=FileStorageKeys.PERMANENT_REMOTE_STORAGE,
            )
        if execution_source == ExecutionSource.TOOL.value:
            fs_instance = EnvHelper.get_storage(
                storage_type=StorageType.TEMPORARY,
                env_name=FileStorageKeys.TEMPORARY_REMOTE_STORAGE,
            )

        if not fs_instance.exists(extract_file_path):
            raise FileNotFoundError(
                f"The file at path '{extract_file_path}' does not exist."
            )
        context = fs_instance.read(path=extract_file_path, encoding="utf-8", mode="rb")
    else:
        if not os.path.exists(extract_file_path):
            raise FileNotFoundError(
                f"The file at path '{extract_file_path}' does not exist."
            )

        with open(extract_file_path, encoding="utf-8") as file:
            context = file.read()

    prompt = construct_prompt(
        preamble=tool_settings.get(PSKeys.PREAMBLE, ""),
        prompt=output["promptx"],
        postamble=tool_settings.get(PSKeys.POSTAMBLE, ""),
        grammar_list=tool_settings.get(PSKeys.GRAMMAR, []),
        context=context,
        platform_postamble="",
    )

    try:
        line_item_extraction = line_item_extraction_plugin["entrypoint_cls"](
            llm=llm,
            tool_settings=tool_settings,
            output=output,
            prompt=prompt,
            structured_output=structured_output,
            logger=app.logger,
        )
        answer = line_item_extraction.run()
        structured_output[output[PSKeys.NAME]] = answer
        metadata[PSKeys.CONTEXT][output[PSKeys.NAME]] = [context]
        return structured_output
    except line_item_extraction_plugin["exception_cls"] as e:
        msg = f"Couldn't extract table. {e}"
        raise APIError(message=msg)
