from typing import Any, Optional

from unstract.prompt_service_v2.constants import DBTableV2
from unstract.prompt_service_v2.extensions import db
from unstract.prompt_service_v2.utils.env_loader import get_env_or_die

DB_SCHEMA = get_env_or_die("DB_SCHEMA", "unstract")


class DBUtils:

    @classmethod
    def get_organization_from_bearer_token(
        cls, token: str
    ) -> tuple[Optional[int], str]:
        """Retrieve organization ID and identifier using a bearer token.

        Args:
            token (str): The bearer token (platform key).

        Returns:
            tuple[int, str]: organization uid and organization identifier
        """
        platform_key_table = f'"{DB_SCHEMA}".{DBTableV2.PLATFORM_KEY}'
        organization_table = f'"{DB_SCHEMA}".{DBTableV2.ORGANIZATION}'

        organization_uid: Optional[int] = cls.execute_query(
            f"SELECT organization_id FROM {platform_key_table} WHERE key=%s", (token,)
        )
        if organization_uid is None:
            return None, None

        organization_identifier: Optional[str] = cls.execute_query(
            f"SELECT organization_id FROM {organization_table} WHERE id=%s",
            (organization_uid,),
        )
        return organization_uid, organization_identifier

    @classmethod
    def execute_query(cls, query: str, params: tuple = ()) -> Any:
        cursor = db.execute_sql(query, params)
        result_row = cursor.fetchone()
        cursor.close()
        if not result_row or len(result_row) == 0:
            return None
        return result_row[0]
