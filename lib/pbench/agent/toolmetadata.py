import json


class ToolMetadataError(Exception):
    pass


class ToolMetadata:
    def __init__(self, inst_dir=None):
        if inst_dir is None:
            self._json_path = None
            self._data = None
            return

        json_path = inst_dir / "tool-scripts" / "meta.json"
        try:
            self._json_path = json_path.resolve(strict=True)
        except FileNotFoundError:
            raise ToolMetadataError(f"missing {json_path}")
        except Exception:
            raise
        try:
            with self._json_path.open("r") as json_file:
                metadata = json.load(json_file)
        except FileNotFoundError:
            self._data = None
        except Exception:
            raise
        else:
            ToolMetadata._validate_metadata(metadata)
            self._data = metadata

    @staticmethod
    def _validate_metadata(metadata):
        if "persistent" not in metadata:
            raise ToolMetadataError("Missing persistent tools")
        if "transient" not in metadata:
            raise ToolMetadataError("Missing transient tools")
        for tool in metadata["persistent"].keys():
            if tool in metadata["transient"].keys():
                raise ToolMetadataError(
                    f"Tool {tool} found in both transient and persistent tool lists"
                )
        for tool in metadata["transient"].keys():
            if tool in metadata["persistent"].keys():
                raise ToolMetadataError(
                    f"Tool {tool} found in both persistent and transient tool lists"
                )

    @classmethod
    def tool_md_from_dict(cls, metadata):
        ToolMetadata._validate_metadata(metadata)
        tmd = cls()
        tmd._data = metadata
        return tmd

    def getFullData(self):
        return self._data

    def getPersistentTools(self):
        return list(self._data["persistent"].keys())

    def getTransientTools(self):
        return list(self._data["transient"].keys())

    def getProperties(self, tool):
        try:
            tool_prop = self._data["transient"][tool]
        except KeyError:
            try:
                tool_prop = self._data["persistent"][tool]
            except KeyError:
                tool_prop = None
        return tool_prop
