from pathlib import Path
from typing import Any, Union

from file_management.file_management_helper import FileManagerHelper
from utils.file_storage.constants import FileStorageConstants, FileStorageType
from utils.file_storage.helpers.common_file_helper import FileStorageHelper

from unstract.core.utilities import UnstractUtils


class PromptStudioFileHelper:
    @staticmethod
    def get_or_create_prompt_studio_subdirectory(
        org_id: str, user_id: str, tool_id: str, is_create: bool
    ) -> str:
        """Resolves a directory path meant for a user running prompt studio.

        Args:
            org_id (str): Organization ID
            user_id (str): User ID
            tool_id (str): ID of the prompt studio tool
            is_create (bool): Flag to create the directory

        Returns:
            str: The absolute path to the directory meant for prompt studio
        """
        base_path = UnstractUtils.get_env(
            env_key=FileStorageConstants.REMOTE_PROMPT_STUDIO_FILE_PATH
        )
        file_path = str(Path(base_path) / org_id / user_id / tool_id)
        extract_file_path = str(Path(file_path) / "extract")
        summarize_file_path = str(Path(file_path) / "summarize")
        if is_create:
            fs_instance = FileStorageHelper.initialize_file_storage(
                type=FileStorageType.PERMANENT
            )
            fs_instance.mkdir(file_path, create_parents=True)
            fs_instance.mkdir(extract_file_path, create_parents=True)
            fs_instance.mkdir(summarize_file_path, create_parents=True)
        return str(file_path)

    @staticmethod
    def upload_for_ide(
        org_id: str, user_id: str, tool_id: str, uploaded_file: Any
    ) -> None:
        fs_instance = FileStorageHelper.initialize_file_storage(
            type=FileStorageType.PERMANENT
        )
        file_system_path = (
            PromptStudioFileHelper.get_or_create_prompt_studio_subdirectory(
                org_id=org_id,
                is_create=True,
                user_id=user_id,
                tool_id=str(tool_id),
            )
        )
        file_path = str(Path(file_system_path) / uploaded_file.name)
        fs_instance.write(path=file_path, mode="wb", data=uploaded_file.read())

    @staticmethod
    def fetch_file_contents(
        org_id: str, user_id: str, tool_id: str, file_name: str
    ) -> Union[bytes, str]:
        fs_instance = FileStorageHelper.initialize_file_storage(
            type=FileStorageType.PERMANENT
        )
        # Fetching legacy file path for lazy copy
        # This has to be removed once the usage of FS APIs
        # are standadized.
        legacy_file_system_path = FileManagerHelper.handle_sub_directory_for_tenants(
            org_id=org_id,
            user_id=user_id,
            tool_id=tool_id,
            is_create=False,
        )

        file_system_path = (
            PromptStudioFileHelper.get_or_create_prompt_studio_subdirectory(
                org_id=org_id,
                is_create=False,
                user_id=user_id,
                tool_id=str(tool_id),
            )
        )
        # TODO : Handle this with proper fix
        # Temporary Hack for frictionless onboarding as the user id will be empty
        if not fs_instance.exists(file_system_path):
            file_system_path = (
                PromptStudioFileHelper.get_or_create_prompt_studio_subdirectory(
                    org_id=org_id,
                    is_create=True,
                    user_id="",
                    tool_id=str(tool_id),
                )
            )
        file_path = str(Path(file_system_path) / file_name)
        legacy_file_path = str(Path(legacy_file_system_path) / file_name)
        file_content_type = fs_instance.mime_type(file_path)
        text_content: Union[bytes, str]
        if file_content_type == "application/pdf":
            # Read contents of PDF file into a string
            text_content = fs_instance.read(
                path=file_path, mode="rb", legacy_storage_path=legacy_file_path
            )

        elif file_content_type == "text/plain":
            text_content = fs_instance.read(
                path=file_path, mode="r", legacy_storage_path=legacy_file_path
            )

        return text_content

    @staticmethod
    def delete_for_ide(org_id: str, user_id: str, tool_id: str, file_name: str) -> bool:
        fs_instance = FileStorageHelper.initialize_file_storage(
            type=FileStorageType.PERMANENT
        )
        file_system_path = (
            PromptStudioFileHelper.get_or_create_prompt_studio_subdirectory(
                org_id=org_id,
                is_create=True,
                user_id=user_id,
                tool_id=str(tool_id),
            )
        )
        # Delete the source file
        fs_instance.rm(str(Path(file_system_path) / file_name))
        # Delete all related files for cascade delete
        # directories = ["extract/", "extract/metadata/", "summarize/"]
        # base_file_name = f"{file_system_path}/{file_name}"
        # TODO : Delete related files
        return True
