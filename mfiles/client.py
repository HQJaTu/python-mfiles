# Standard modules
import json
import logging
from copy import deepcopy

# External modules
from http import HTTPStatus
from os import getcwd
from os.path import (splitext as os_splitext, join as os_join)
from typing import Optional

# Internal modules
from mfiles.base_client import MFilesClientBase
from mfiles.definitions import DATATYPE, LOOKUP_DATATYPE, LOOKUP_DATATYPES, \
    OBJ, OBJ_PROPERTY
from mfiles.errors import MFilesClientException, MFilesServerException

# M-files server info
DEFAULT_URL = "http://localhost/m-files/REST/"

log = logging.getLogger(__name__)


class MFilesClient(MFilesClientBase):
    """M-Files REST API client methods.

    For more information, see:
    https://developer.m-files.com/APIs/REST-API/Reference
    """

    # pylint: disable=too-many-public-methods

    def __init__(self, server: str = DEFAULT_URL, user: str = None, password: str = None, vault: str = None):
        """
        Constructor for M-Files client.
        :param: server: API URL. Defaults to ``"http://localhost/m-files/REST/"``
        :param: user: User to log in with. If not supplied it will be fetched
                    from environment variable ``MFILES_USER``, if not set
                    it will be fetched using ``input()``.
        :param: password: User password. If not supplied it will be
                        fetched from environment variable ``MFILES_PASS``,
                        if not set it will be fetched using ``getpass()``.
        :param: vault: M-Files vault GUID to connect to.
        """
        MFilesClientBase.__init__(self, server, user, password, vault)

    def quick_search(self, query: str) -> dict:
        """
        Perform a quick search in the M-Files vault.

        This returns the same results as if the query was
        performed against the M-Files client search box.

        :param: query: Search query.
        :returns: dict: Matching items.
        """
        search_query = "objects?q=" + query
        return self.get(search_query)

    def search(self, query):
        """
        Perform a search in the M-Files vault.

        :param: query: Search query.
        :returns: list: A list of matching items.
        """
        search_query = "objects?" + query
        return self.get(search_query)

    def objects(self) -> list:
        """
        Get all object types in the M-Files vault.
        :returns: list: A list of matching items.
        """
        response = self.get("structure/objecttypes")
        return response

    def classes(self) -> list:
        """
        Get all classes in the M-Files vault.
        :returns: list: A list of matching items.
        """
        response = self.get("structure/classes")
        return response

    def properties(self) -> list:
        """
        Get all property definitions in the M-Files vault.
        :returns: list: A list of matching items.
        """
        response = self.get("structure/properties")
        return response

    def class_details(self, class_id: int) -> dict:
        """
        Get details for a specific class in the M-Files vault.
        :param: class_id: Class ID to query for.
        :returns: list: A list of matching items.
        """
        endpoint = "structure/classes/{}".format(class_id)
        response = self.get(endpoint)
        return response

    def value_lists(self) -> list:
        """
        Get all value lists in the M-Files vault.
        :returns: list: A list of matching items.
        """
        response = self.get("valuelists")
        return response

    def value_list_items(self, list_id: int) -> dict:
        """
        Get items for a specific value list in the M-Files vault.
        :returns: list: A list of matching items.
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
        :returns: dict: ID of value in value list.
        :rtype: int
        :raises: MFilesClientException: If the value name can't be found in the list.
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
        :returns: List of dicts with information about the types.
        :rtype list
        :raises MFilesClientException: If the category supplied doesn't exist.
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

    def get_info(self, name: str, category: str = "object") -> dict:
        """
        Get general info of a type by name.

        :param: name: Name of type to get info from.
        :param: category: Type category. Can be any of ``"object"``, ``"class"``, ``"property"``.
        Defaults to ``"object"``.
        :returns: dict: Dictionary with information about the type.
        :raises MFilesClientException: If the name can't be found.
        """
        types = self.get_types(category)
        for type_info in types:
            if type_info["Name"] == name:
                return type_info
        raise MFilesClientException("Property '{}' could not be found in vault".format(name))

    def get_info_id(self, type_id: str, category: str = "object") -> dict:
        """
        Get general info of a type by id.

        :param: type_id: ID of type to get info from.
        :param: category: Type category. Can be any of ``"object"``, ``"class"``, ``"property"``.
        Defaults to ``"object"``.
        :returns: dict: Dictionary with information about the type.
        :raises MFilesClientException: If the name can't be found.
        """
        types = self.get_types(category)
        for type_info in types:
            if type_info["ID"] == type_id:
                return type_info
        raise MFilesClientException("Property ID {} could not be found in vault".format(type_id))

    def translate_name(self, name: str, category: str = "object") -> str:
        """
        Translate a name into its ID as recognized by the server.

        :param: name: Name to translate.
        :param: category: Type category. Can be any of ``"object"``, ``"class"``, ``"property"``.
        Defaults to ``"object"``.
        :returns: str: ID of ``name``.
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

        :param: file_path: Path to file to be uploaded.
        :param: object_type: Object type.
        If integer, the type will not be attempted to be translated.
        If str, the type will be translated into the property ID the server expects for the given type.
        :param: object_class: Object class, same translation principle as for object_type.
        :param: extra_info: Additional object information.
        :returns: Dictionary with API request result.
        :raises MFilesException: If the file can't be uploaded.
        """
        # Upload file to temporary storage
        endpoint = "files"
        with open(file_path, mode="rb") as file_stream:
            content = file_stream.read()
        upload_info = self.post(endpoint, content)

        # Create object
        object_name, objext_ext = os_splitext(file_path)
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

        :param: object_type (int): Object type ID.
        :param: object_id (int): Object ID.
        :param: file_id (int): File ID.
        :param: object_version (int, str): Object version. Defaults to latest
        :returns: True if file is found and downloaded successfully.
        :rtype: bool
        :raises: MFilesServerException: If the file can't be downloaded.
        """
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        request_url = "objects/{}/{}/{}/files/{}/content".format(object_type, object_id, object_version,
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
        local_path = local_path or os_join(getcwd(), file_name)
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
        request_url = "objects/{}/{}/latest?allVersions=true".format(object_type, object_id)
        response = self.session.delete(request_url)
        if response.status_code != HTTPStatus.OK:
            raise MFilesServerException(response.text)

        return response
