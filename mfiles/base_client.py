# Standard modules
from getpass import getpass
import json
from os import getenv
from enum import Enum
from typing import Optional

# External modules
import requests
from urllib.parse import urlsplit
from http import HTTPStatus
import logging

# Internal modules
from mfiles.errors import MFilesClientException, MFilesServerException

log = logging.getLogger(__name__)


class MFilesClientBase:
    """
    M-Files REST API client non-business logic.

    For more information, see:
    https://developer.m-files.com/APIs/REST-API/Reference
    """

    # pylint: disable=too-many-public-methods

    class TokenType(Enum):
        SERVER = 1
        VAULT = 2

    def __init__(self, server: str, user: Optional[str], password: Optional[str], vault: Optional[str] = None):
        """
        Constructor for M-Files client.
        :param: server: API URL
        :param: user: User to log in with. If not supplied it will be fetched
                    from environment variable ``MFILES_USER``, if not set
                    it will be fetched using ``input()``.
        :param: password: User password. If not supplied it will be
                        fetched from environment variable ``MFILES_PASS``,
                        if not set it will be fetched using ``getpass()``.
        :param: vault: M-Files vault GUID to connect to.
        """
        self.session = requests.Session()
        self._server = None
        self._user = None
        self._password = None
        self._vault = None
        self._server_token = None
        self._vault_token = None
        self.user = user
        self.password = password
        self.vault = vault
        self.server = server

    @property
    def server(self) -> str:
        return self._server

    @server.setter
    def server(self, server: str) -> None:
        """
        Set the M-Files server API URL.
        Typical format for API URL is: https://vault-hostname.example.com/REST/
        :param: server: API URL.
            If not supplied it will be fetched from environment variable MFILES_URL
        """
        env_server = getenv("MFILES_URL")
        self._server = server or env_server

        parts = urlsplit(self.server)
        if parts.fragment or parts.query:
            raise MFilesClientException(f"M-Files REST API URL '{self.server}' can not contain query or fragment!")

        if parts.path[-1] != "/":
            self.server += "/"

        if "REST" not in self.server:
            log.warning(f"Typical M-Files REST API URLs have /REST/ in them.")

    @property
    def user(self) -> str:
        return self._user

    @user.setter
    def user(self, user: str) -> None:
        """
        Set the M-Files user.
        :param: user: User to login with.
            If not supplied it will be fetched from environment variable MFILES_USER
        """
        env_user = getenv("MFILES_USER")
        programmatic_user = user or env_user
        self._user = programmatic_user or input("M-Files mail: ")

    @property
    def password(self) -> str:
        return self._password

    @password.setter
    def password(self, password: str) -> None:
        """
        Set the M-Files user password.
        :param: password: User password.
            If not supplied it will be fetched from environment variable MFILES_PASS
        """
        env_pass = getenv("MFILES_PASS")
        programmatic_pass = password or env_pass
        self._password = programmatic_pass or getpass("M-Files password: ")

    @property
    def vault(self) -> str:
        return self._vault

    @vault.setter
    def vault(self, vault: str) -> None:
        """
        Set the M-Files vault GUID to connect to.
        :param: vault: M-Files vault GUID to connect to.
            If not supplied it will be fetched from environment variable MFILES_VAULT
        """
        env_vault = getenv("MFILES_VAULT")
        self._vault = vault or env_vault
        self.vault_token = None

    @property
    def server_token(self):
        return self._server_token

    @server_token.setter
    def server_token(self, token: str) -> None:
        self._server_token = token
        self.session.headers = {"X-Authentication": self._server_token}

    @property
    def vault_token(self):
        return self._vault_token

    @vault_token.setter
    def vault_token(self, token: str) -> None:
        self._vault_token = token
        self.session.headers = {"X-Authentication": self._vault_token}

    def login(self) -> MFilesClientBase:
        """
        Logs in and prepares the authentication token, ready to be used in
        HTTP request header as authentication.
        """
        auth_payload = json.dumps(
            {
                "Username": self.user,
                "Password": self.password,
                "VaultGuid": self.vault
            }
        )
        request_url = self.server + "server/authenticationtokens"
        response = self.session.post(request_url, data=auth_payload)
        response.raise_for_status()
        response_json = json.loads(response.text)
        if "Value" not in response_json:
            raise MFilesServerException("M-Files authentication failed!")

        if self.vault is not None:
            self.vault_token = response_json["Value"]

            return self

        # No vault was specified.
        # Go get a list of vaults and use the first available one
        self.server_token = response_json["Value"]
        vaults = self.get('server/vaults', token_type=self.TokenType.SERVER)
        if vaults is None or len(vaults) == 0:
            raise MFilesServerException("M-Files authentication succeeded, but you don't have access to any vaults!")
        vault = vaults[0]
        if "Authentication" not in vault:
            raise MFilesServerException("M-Files authentication failed! Invalid vault listing response received.")
        self.vault_token = vault['Authentication']

        return self

    def _headers(self, token_type: Optional[TokenType] = None) -> dict:
        headers = {}

        if token_type is not None:
            if token_type == self.TokenType.SERVER:
                if self.server_token is None:
                    raise MFilesClientException("There is no server token to be used!")
                headers["X-Authentication"] = str(self.server_token)
            elif token_type == self.TokenType.VAULT:
                if self.vault_token is None:
                    raise MFilesClientException("There is no vault token to be used!")
                headers["X-Authentication"] = str(self.vault_token)

            return headers

        if self.vault is None:
            if self.server_token is not None:
                headers["X-Authentication"] = str(self.server_token)
        else:
            if self.vault_token is not None:
                headers["X-Authentication"] = str(self.vault_token)

        return headers

    def _login_if_needed(self, required_token_type: TokenType) -> None:
        """
        Helper: Determine if login is needed.
        Login if required token missing.
        :param: required_token_type: Token to check existence for
        """
        if required_token_type == self.TokenType.SERVER and self.server_token is None:
            log.warning("No server authentication token provided. Attempt logging in.")
            self.login()
        if required_token_type == self.TokenType.VAULT and self.vault_token is None:
            if self.vault is None:
                raise MFilesClientException("There is no vault defined! Cannot get vault token for it.")
            log.warning("No vault authentication token provided. Attempt logging in.")
            self.login()

    def get(self, endpoint: str, token_type: TokenType = TokenType.VAULT) -> dict:
        """
        General purpose GET method.

        :param: endpoint: Endpoint on form ``"path/to/endpoint"``.
        :param: token_type: Token to use for this operation. Defaults to ``TokenType.VAULT``.
        :returns: dict: Dictionary with request result.
        :raises MFilesServerException: If request returns status code != 200.
        """

        # Sanity:
        if endpoint[0] == "/":
            raise MFilesClientException("Endpoint can not start with a / !")
        self._login_if_needed(token_type)

        # Go for a GET-request
        request_url = self.server + endpoint
        response = self.session.get(request_url, headers=self._headers(token_type))
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        return response.json()

    def put(self, endpoint: str, data: str = None, token_type: TokenType = TokenType.VAULT) -> dict:
        """
        General purpose PUT method.

        :param: endpoint: Endpoint on form ``"path/to/endpoint"``.
        :param: data: Data to use in PUT request.
        :param: token_type: Token to use for this operation. Defaults to ``TokenType.VAULT``.
        :returns: dict: Dictionary with request result.
        :raises MFilesServerException: If request returns status code != 200.
        """

        # Sanity:
        if endpoint[0] == "/":
            raise MFilesClientException("Endpoint can not start with a / !")
        self._login_if_needed(token_type)

        # Go for a PUT-request
        request_url = self.server + endpoint + "?_method=PUT"
        response = self.session.post(request_url, data=data, headers=self._headers())
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        return response.json()

    def post(self, endpoint, data=None, token_type: TokenType = TokenType.VAULT) -> dict:
        """
        General purpose POST method.

        :param: endpoint: Endpoint on form ``"path/to/endpoint"``.
        :param: data: Data to use in POST request.
        :param: token_type: Token to use for this operation. Defaults to ``TokenType.VAULT``.
        :returns: dict: Dictionary with request result.
        :raises MFilesServerException: If request returns status code != 200.
        """

        # Sanity:
        if endpoint[0] == "/":
            raise MFilesClientException("Endpoint can not start with a / !")
        self._login_if_needed(token_type)

        # Go for a PUT-request
        request_url = self.server + endpoint
        response = self.session.post(request_url, data=data, headers=self._headers())
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        return response.json()
