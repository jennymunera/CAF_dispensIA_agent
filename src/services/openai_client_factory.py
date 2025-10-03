import logging
import os
from typing import Optional

from azure.identity import DefaultAzureCredential
from openai import OpenAI

_LOGGER = logging.getLogger(__name__)


class OpenAIClientFactory:
    def __init__(
        self,
        endpoint_env: str = "AZURE_OPENAI_ENDPOINT",
        use_api_key_env: str = "USE_API_KEY",
        api_key_env: str = "AZURE_OPENAI_API_KEY",
    ) -> None:
        self._endpoint_env = endpoint_env
        self._use_api_key_env = use_api_key_env
        self._api_key_env = api_key_env

    def _build_base_url(self, endpoint: str) -> str:
        endpoint = endpoint.rstrip("/")
        return f"{endpoint}/openai/v1/"

    def _create_with_api_key(self, base_url: str, api_key: str) -> OpenAI:
        return OpenAI(base_url=base_url, api_key=api_key)

    def _create_with_aad(self, base_url: str) -> OpenAI:
        credential = DefaultAzureCredential()

        def token_provider() -> str:
            return credential.get_token("https://cognitiveservices.azure.com/.default").token

        return OpenAI(base_url=base_url, azure_ad_token_provider=token_provider)

    def create_client(self) -> OpenAI:
        endpoint = os.getenv(self._endpoint_env)
        if not endpoint:
            raise ValueError(
                "La variable de entorno 'AZURE_OPENAI_ENDPOINT' es obligatoria para crear el cliente de OpenAI"
            )

        base_url = self._build_base_url(endpoint)

        use_api_key = os.getenv(self._use_api_key_env, "false").lower() == "true"
        if use_api_key:
            api_key = os.getenv(self._api_key_env)
            if not api_key:
                raise ValueError(
                    "Se indicó el uso de API Key pero 'AZURE_OPENAI_API_KEY' no está configurado"
                )
            _LOGGER.info("Autenticando contra Azure OpenAI mediante API Key")
            return self._create_with_api_key(base_url, api_key)

        _LOGGER.info("Autenticando contra Azure OpenAI mediante Azure AD")
        return self._create_with_aad(base_url)
