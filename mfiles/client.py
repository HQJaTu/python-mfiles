"""M-Files client methods.

For more information, see:
https://developer.m-files.com/APIs/REST-API/Reference
"""

# Standard modules
from copy import deepcopy
from getpass import getpass
import json
from os import getcwd, getenv
from os.path import splitext
from enum import Enum

# External modules
import requests
from urllib.parse import urlsplit
from http import HTTPStatus
import logging

# Internal modules
from mfiles.definitions import DATATYPE, LOOKUP_DATATYPE, LOOKUP_DATATYPES, \
    OBJ, OBJ_PROPERTY
from mfiles.errors import MFilesClientException, MFilesServerException

# M-files server info
DEFAULT_URL = "http://localhost/m-files/REST/"

log = logging.getLogger(__name__)


class MFilesClient():
    """
    M-Files REST API client.
    """

    # pylint: disable=too-many-public-methods

    class TokenType(Enum):
        SERVER = 1
        VAULT = 2

    def __init__(self, server: str = DEFAULT_URL, user: str = None, password: str = None, vault: str = None):
        """
        Constructor for M-Files client.
        :param server: API URL. Defaults to ``"http://localhost/m-files/REST/"``
        :param user: User to login with. If not supplied it will be fetched
                    from environment variable ``MFILES_USER``, if not set
                    it will be fetched using ``input()``.
        :param password: User password. If not supplied it will be
                        fetched from environment variable ``MFILES_PASS``,
                        if not set it will be fetched using ``getpass()``.
        :param vault: M-Files vault GUID to connect to.
        """
        self._server = None
        self._user = None
        self._password = None
        self._vault = None
        self._server_token = None
        self._vault_token = None
        self.user = user
        self.password = password
        self.vault = vault
        self.session = requests.Session()
        self.server = server

    @property
    def server(self) -> str:
        return self._server

    @server.setter
    def server(self, server: str) -> None:
        """
        Set the M-Files server API URL.
        Typical format for API URL is: https://vault-hostname.example.com/REST/
        :param server: API URL.
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
        :param user: User to login with.
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
        :param password: User password.
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
        :param vault: M-Files vault GUID to connect to.
            If not supplied it will be fetched from environment variable MFILES_VAULT
        :returns: MFilesClient object.
        """
        env_vault = getenv("MFILES_VAULT")
        self._vault = vault or env_vault

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

    def login(self) -> MFilesClient:
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

    def get(self, endpoint: str, token_type: TokenType = TokenType.VAULT) -> dict:
        """
        General purpose GET method.

        :param endpoint: Endpoint on form ``"path/to/endpoint"``.
        :return dict: Dictionary with request result.
        :raise MFilesServerException: If request returns status code != 200.
        """

        # Sanity:
        if endpoint[0] == "/":
            raise MFilesClientException("Endpoint can not start with a / !")
        if token_type == self.TokenType.SERVER and self.server_token is None:
            log.warning("No server authentication token provided. Attempt logging in.")
            self.login()
        if token_type == self.TokenType.VAULT and self.vault_token is None:
            if self.vault is None:
                raise MFilesClientException("There is no vault defined! Cannot get vault token for it.")
            log.warning("No vault authentication token provided. Attempt logging in.")
            self.login()

        # Go for a GET-request
        request_url = self.server + endpoint
        response = self.session.get(request_url, headers=self._headers(token_type))
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        return response.json()

    def put(self, endpoint: str, data=None) -> dict:
        """
        General purpose PUT method.

        :param endpoint: Endpoint on form ``"path/to/endpoint"``.
        :param data (str): Data to use in PUT request.
        :return dict: Dictionary with request result.
        :raise MFilesServerException: If request returns status code != 200.
        """

        # Sanity:
        if endpoint[0] == "/":
            raise MFilesClientException("Endpoint can not start with a / !")
        if self.token is None:
            log.warning("No authentication token provided. Attempt logging in.")
            self.login()

        # Go for a PUT-request
        request_url = self.server + endpoint + "?_method=PUT"
        response = self.session.post(request_url, data=data, headers=self._headers())
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        return response.json()

    def post(self, endpoint, data=None):
        """
        General purpose POST method.

        :param endpoint: Endpoint on form ``"path/to/endpoint"``.
        :param data (str): Data to use in POST request.
        :return dict: Dictionary with request result.
        :raise MFilesServerException: If request returns status code != 200.
        """

        # Sanity:
        if endpoint[0] == "/":
            raise MFilesClientException("Endpoint can not start with a / !")
        if self.token is None:
            log.warning("No authentication token provided. Attempt logging in.")
            self.login()

        # Go for a PUT-request
        request_url = self.server + endpoint
        response = self.session.post(request_url, data=data, headers=self._headers())
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        return response.json()

    def quick_search(self, query: str) -> list:
        """
        Perform a quick search in the M-Files vault.

        This returns the same results as if the query was
        performed against the M-Files client search box.

        :param query: Search query.
        :return list: A list of matching items.
        """
        search_query = "objects?q=" + query
        return self.get(search_query)

    def search(self, query):
        """
        Perform a search in the M-Files vault.

        :param query: Search query.
        :return list: A list of matching items.
        """
        search_query = "objects?" + query
        return self.get(search_query)

    def objects(self) -> list:
        """
        Get all object types in the M-Files vault.
        """
        response = self.get("structure/objecttypes")
        return response

    def classes(self) -> list:
        """
        Get all classes in the M-Files vault.
        """
        response = self.get("structure/classes")
        return response

    def properties(self) -> list:
        """
        Get all property definitions in the M-Files vault.
        """
        response = self.get("structure/properties")
        return response

    def class_details(self, class_id: int) -> dict:
        """
        Get details for a specific class in the M-Files vault.
        """
        endpoint = "structure/classes/{}".format(class_id)
        response = self.get(endpoint)
        return response

    def value_lists(self) -> list:
        """
        Get all value lists in the M-Files vault.
        """
        response = self.get("valuelists")
        return response

    def value_list_items(self, list_id: int) -> dict:
        """
        Get items for a specific value list in the M-Files vault.
        """
        endpoint = "valuelists/{}/items".format(list_id)
        response = self.get(endpoint)
        return response

    def get_value_id(self, value_name: str, list_id: int, owner_ids: list) -> int:
        """
        Get the ID of a specific value in a specific value list.

        :param: value_name: Name of the value list option to look for.
        :param: list_id: ID of the list to look in.
        :param: owner_ids: IDs of potential list owners.
        :return dict: ID of value in value list.
        :rtype int
        :raise MFilesClientException: If the value name can't be found in the list.
        """
        list_items = self.value_list_items(list_id)
        for item in list_items["Items"]:
            same_name = item["Name"] == value_name
            ok_owner = not item["HasOwner"] or item["OwnerID"] in owner_ids
            if same_name and ok_owner:
                return item["ID"]

        raise MFilesClientException("Value name '{}' not recognized".format(value_name))

    def get_types(self, category: str = "object") -> list:
        """
        Get info for all types from a type category.

        :param: category: Type category. Can be any of ``"object"``,
                            ``"class"``, ``"property"``. Defaults to
                            ``"object"``.
        :return List of dicts with information about the types.
        :rtype list
        :raise MFilesClientException: If the category supplied doesn't exist.
        """
        if category == "object":
            types = self.objects()
        elif category == "class":
            types = self.classes()
        elif category == "property":
            types = self.properties()
        else:
            raise MFilesClientException("Type name {} not recognized".format(category))
        return types

    def get_info(self, name, category="object"):
        """
        Get general info of a type by name.

        Parameters:
            name (str): Name of type to get info from.
            category (str): Type name. Can be any of ``"object"``,
                            ``"class"``, ``"property"``. Defaults to
                            ``"object"``.

        Raises:
            MFilesException: If the property name can't be found.

        Returns:
            dict: Dictionary with information about the type.
        """
        types = self.get_types(category)
        for type_info in types:
            if type_info["Name"] == name:
                return type_info
        raise MFilesClientException("Property '{}' could not be found in vault".format(name))

    def get_info_id(self, type_id, category="object"):
        """
        Get general info of a type by id.

        Parameters:
            type_id (str): ID of type to get info from.
            category (str): Type category. Can be any of ``"object"``,
                            ``"class"``, ``"property"``. Defaults to
                            ``"object"``.

        Raises:
            MFilesException: If the property ID can't be found.

        Returns:
            dict: Dictionary with information about the type.
        """
        types = self.get_types(category)
        for type_info in types:
            if type_info["ID"] == type_id:
                return type_info
        raise MFilesClientException("Property ID {} could not be found in vault".format(type_id))

    def translate_name(self, name, category="object"):
        """
        Translate a name into its ID as recognized by the server.

        Parameters:
            name (str): Name to translate.
            category (str): Type category. Can be any of ``"object"``,
                            ``"class"``, ``"property"``. Defaults to
                            ``"object"``.

        Returns:
            int: ID of ``name``.
        """
        return self.get_info(name, category)["ID"]

    def get_property(self, property_name, owners, property_value):
        """
        Get a certain property built as M-Files expects it.

        Parameters:
            property_name (str): Property name.
            owners (list): List of ints with possible owners IDs.
            property_value (any): Value to set property to.

        Return:
            dict: Property with required keys and values.
        """
        property_info = self.get_info(property_name, "property")
        prop = deepcopy(OBJ_PROPERTY)
        prop["PropertyDef"] = property_info["ID"]
        prop["TypedValue"]["DataType"] = property_info["DataType"]
        if property_info["DataType"] in LOOKUP_DATATYPES:
            # DataType needs to be looked up
            datatype_id = self.get_value_id(property_value,
                                            property_info["ValueList"],
                                            owners)
            datatype = deepcopy(LOOKUP_DATATYPE)
            datatype["Lookup"]["Item"] = datatype_id
        else:
            datatype = deepcopy(DATATYPE)
            datatype["Value"] = property_value
        prop["TypedValue"].update(datatype)
        return prop

    def create_object(self, name, object_type=0, object_class=0,
                      extra_info=None, file_info=None):
        """
        Create M-Files object and upload it to the vault.

        Parameters:
            name (str): Name of new object.
            object_type (str, int): Object type. If integer, the type will
                                    not be attempted to be translated. If
                                    string, the type will be transated into
                                    the property ID the server expects for the
                                    given type.
            object_class (str, int): Object class, same translation principle
                                     as for object_type.
            extra_info (dict): Additional object information.
            file_info (dict): Eventual file information for object. Dict
                              that must contain keys ``UploadID``, ``Title``,
                              ``Extension``, ``Size``.

        Raises:
            MFilesException: If the object can't be created.

        Returns:
            dict: Dictionary with object information.
        """
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        extra_info = extra_info or {}
        file_info = file_info or []
        if isinstance(object_type, str):
            object_type = self.translate_name(object_type, "object")
        if isinstance(object_class, str):
            object_class = self.translate_name(object_class, "class")
        # Start building object
        obj = deepcopy(OBJ)
        # Set mandatory info
        obj["PropertyValues"][0]["TypedValue"]["Value"] = name
        obj["PropertyValues"][1]["TypedValue"]["Lookup"]["Item"] = object_class
        # Add any additionally supplied properties
        for property_name in extra_info:
            owners = [object_class, object_type]
            prop = self.get_property(property_name, owners,
                                     extra_info[property_name])
            obj["PropertyValues"].append(prop)
        obj["Files"] = [file_info]
        data = json.dumps(obj)
        endpoint = "objects/{}".format(object_type)
        return self.post(endpoint, data)

    def check_out(self, object_id, object_version="latest", object_type=0):
        """
        Check out an object from M-Files.
        """
        data = json.dumps({"Value": "2"})  # Checked out by me
        endpoint = "objects/{}/{}/{}/checkedout".format(object_type, object_id, object_version)
        return self.put(endpoint, data)

    def check_in(self, object_id, object_version="latest", object_type=0):
        """
        Check in an object to M-Files.
        """
        data = json.dumps({"Value": "0"})  # Checked in
        endpoint = "objects/{}/{}/{}/checkedout".format(object_type, object_id, object_version)
        return self.put(endpoint, data)

    def upload_file(self, file_path, object_type=0, object_class=0,
                    extra_info=None):
        """
        Upload a file to M-Files.

        Parameters:
            file_path (str): Path to file to upload.
            object_type (str, int): Object type. If integer, the type will
                                    not be attempted to be translated. If
                                    string, the type will be transated into
                                    the property ID the server expects for the
                                    given type.
            object_class (str, int): Object class, same translation principle
                                     as for object_type.
            extra_info (dict): Additional object information.

        Raises:
            MFilesException: If the file can't be uploaded.

        Returns:
            dict: Dictionary with API request result.
        """
        # Upload file to temporary storage
        endpoint = "files"
        with open(file_path, mode="rb") as file_stream:
            content = file_stream.read()
        upload_info = self.post(endpoint, content)

        # Create object
        object_name, objext_ext = splitext(file_path)
        file_info = {
            "UploadID": upload_info["UploadID"],
            "Title": object_name,
            "Extension": objext_ext[1:],
            "Size": upload_info["Size"]
        }

        obj_info = self.create_object(object_name, object_type, object_class,
                                      extra_info, file_info)
        return obj_info

    def download_file(self, local_path: str, object_type: str, object_id: int, file_id: int,
                      object_version: Optional[str | int] = "latest"):
        """
        Download a file from M-Files.

        :param object_type (int): Object type ID.
        :param object_id (int): Object ID.
        :param file_id (int): File ID.
        :param object_version (int, str): Object version. Defaults to
        :returns True if file is found and downloaded successfully.
        :rtype: bool
        :raises MFilesServerException: If the file can't be downloaded.
        """
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        request_url = "{}objects/{}/{}/{}/files/{}/content".format(self.server, object_type, object_id, object_version,
                                                                   file_id)
        response = self.session.get(request_url)
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)
        with open(local_path, mode="wb+") as file_stream:
            file_stream.write(response.content)
        return True

    def download_file_name(self, file_name: str, local_path: str = None):
        """
        Download a file from M-Files by its name.

        Caution:
            This searches for the file and downloads the top
            result. This is not always guaranteed to be the
            intended file. A better way is to use search to
            find the correct file and then use the function
            ``download_file()`` to download the file by using
            file and object id.

        Parameters:
            file_name (str): Name of file to download.
            local_path (str): Path to download file to. Defaults
                            to file name and current directory.

        Returns:
            bool: True if file is found and downloaded.
        """
        items = self.quick_search(file_name)
        if not items:
            return False
        item = items["Items"][0]
        obj_type = item["ObjVer"]["Type"]
        obj_id = item["ObjVer"]["ID"]
        obj_version = item["ObjVer"]["Version"]
        file_id = item["Files"][0]["ID"]
        local_path = local_path or getcwd() + "\\" + file_name
        download_ok = self.download_file(local_path=local_path,
                                         object_type=obj_type,
                                         object_id=obj_id, file_id=file_id,
                                         object_version=obj_version)
        return download_ok

    def delete_object(self, object_type: str, object_id: int) -> dict:
        """
        Delete M-Files object.

        Note:
            Deleting an object means flagging an object for deletion.
            Most users will not see the object anymore, but administators
            will still be able to access it.
        """
        endpoint = "objects/{}/{}/deleted".format(object_type, object_id)
        return self.put(endpoint)

    def destroy_object(self, object_type: str, object_id: int) -> dict:
        """
        Destroy M-Files object.

        Caution:
            Destroying an object means unrecoverably deleting all
            versions of the object. Use with caution.
        """
        request_url = "{}objects/{}/{}/latest?allVersions=true".format(self.server, object_type, object_id)
        response = self.session.delete(request_url)
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)

        return response
