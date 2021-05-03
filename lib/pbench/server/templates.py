import copy
import json
import re
import sys

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, AnyStr, Dict

import pyesbulk

from pbench.common.exceptions import (
    BadDate,
    MappingFileError,
    JsonFileError,
    TemplateError,
)
from pbench.server import tstos
from pbench.server.database.models.template import Template, TemplateNotFound


class JsonFile:
    """
    Describes a single JSON file, which might be a settings file or a
    mapping file.
    """

    def __init__(self, file: Path = None):
        """
        Initialize a JSON file object by resolving the file name and reading
        the modification date.

        Args:
            file: JSON file path. Defaults to None to allow initializing an
                object to store DB query results rather than loading from a
                file.
        """
        if file:
            self.file = file.resolve(strict=True)
            self.modified = datetime.fromtimestamp(self.file.stat().st_mtime)
        else:
            self.file = None
            self.modified = None
        self.json = None

    @staticmethod
    def raw_json(json: Dict[AnyStr, Any]) -> "JsonFile":
        """
        An alternate constructor that can be loaded directly with a JSON
        document in order to capture the data from a Template DB object.

        Returns:
            An instance of JsonFile
        """
        new = JsonFile()
        new.json = json
        return new

    def get_version(self) -> str:
        """
        Parse the metadata version information from the mapping file. This is
        done on standalone template files and on "tool" template files, but
        not on the "base" skeleton files shared by the tool templates. The
        context is under control of the TemplateFile class load methods.

        Raises:
            MappingFileError: Mapping file doesn't contain proper version

        Returns:
            Template file metadata version
        """
        try:
            version = self.json["_meta"]["version"]
        except KeyError as e:
            raise MappingFileError(f"mapping missing {e} in {self.file}: {self.json}")
        return version

    def load(self) -> bool:
        """
        Simple wrapper function to load a JSON object from the object's file,
        raising a JsonFileError when bad JSON data is encountered.

        Raises:
            JsonFileError: Improperly formatted JSON

        Returns:
            True if the file was loaded, False if it had already been loaded
        """

        # Don't load the file again if we've already done it
        if self.json:
            return False
        with self.file.open(mode="r") as jsonfp:
            try:
                data = json.load(jsonfp)
            except ValueError as err:
                raise JsonFileError("{}: {}".format(self.file, err))
        self.json = data
        return True

    def merge(self, name: str, base: "JsonFile"):
        """
        Base class implementation for merge. The base class has no associated
        skeleton document to merge but this no-op implementation allows merge
        to be called on any JsonFile.

        Args:
            name: property name
            base: The base JsonFile
        """
        pass

    def add_mapping(self, name: str, body: Dict[AnyStr, Any]):
        """
        Add a template property sub-document to the mappings.


        Args:
            name: Property name
            body: Subdocument description

        Raises:
            KeyError: the loaded template body doesn't have the expected
                "properties" key.
        """
        self.json["properties"][name] = body


class JsonToolFile(JsonFile):
    """
    Extend the JSON template file handling to provide the capability of merging
    JSON tool templates with a base skeleton.
    """

    def load(self) -> bool:
        """
        Tool mapping files define a sub-document in the Elasticsearch template
        specific to the tool (e.g., "iostat") which exists within a common
        base skeleton. The merge of the two includes elevating the "_meta"
        version from the sub-document into the base document.

        Here we extend the JsonFile load method to remove the sub-document
        metadata and save it to be spliced into the base document by merge.

        Returns:
            True if the file was loaded, False if it had already been loaded
        """
        loaded = super().load()
        if loaded:
            self.meta = self.json["_meta"]
            del self.json["_meta"]
        return loaded

    def get_version(self) -> str:
        """
        Parse the metadata version information from the mapping file. This is
        done on standalone template files and on "tool" template files, but
        not on the "base" skeleton files shared by the tool templates. The
        context is under control of the TemplateFile class load methods.

        This produces a similar result to the superclass method; except that
        JsonToolFile has already sequestered the version metadata to prepare
        for merging with the skeleton.

        Raises:
            MappingFileError: Mapping file doesn't contain proper version

        Returns:
            Template file metadata version
        """
        try:
            version = self.meta["version"]
        except KeyError as e:
            raise MappingFileError(f"mapping missing {e} in {self.file}: {self.meta}")
        return version

    def merge(self, name: str, base: JsonFile):
        """
        Merge a tool-specific sub-document into the common base Elasticsearch
        template document by linking the tool's mapping and meta-version into
        a copy of the base document.

        Args:
            name: property name
            base: The base JsonFile
        """
        tool_mapping = copy.deepcopy(base.json)
        tool_mapping["_meta"] = self.meta
        sub_map = self.json
        self.json = tool_mapping
        self.add_mapping(name, sub_map)


class TemplateFile:
    """
    Describes an Elasticsearch template. This may include both mapping file
    and settings file, as a complete template. Tool templates are built from a
    "base" skeleton and a tool-specific overlay, with a shared JsonFile object
    describing the common framework and a JsonToolFile providing the version
    and tool-specific properties.

    Loading the JSON files from disk is deferred to the resolve() method; this
    will check modification dates against the Template database. We can use the
    DB cached data unless the on-disk JSON is newer, in which case we'll fully
    resolve it and update the DB.
    """

    # Internal fixed "pattern" information for processing index templates; each
    # of these defines properties associated with a particular Elasticsearch
    # index and document template pair. The exception is the final "tool-data"
    # element which describes a set of index/template documents, one for each
    # tool-specific document. (E.g., iostat, pidstat.)
    #
    # Properties:
    #     (key):            The internal reference name.
    #     idxname:          The root name of the Elasticsearch index
    #     template_name:    The document template name to be registered with
    #                       Elasticsearch
    #     template_pat:     The index name to be registered with Elasticsearch
    #     template:         The format of Elasticsearch's generated timeseries
    #                       indices associate with the "template_pat"
    #     owned             Documents using this template are "owned" by a user
    #     desc              A description string reported when templates are
    #                       dumped by the pbench-index command.
    index_patterns = {
        "result-data": {
            "idxname": "result-data",
            "template_name": "{prefix}.v{version}.{idxname}",
            "template_pat": "{prefix}.v{version}.{idxname}.*",
            "template": "{prefix}.v{version}.{idxname}.{year}-{month}-{day}",
            "owned": True,
            "desc": "Daily result data (any data generated by the"
            " benchmark) for all pbench result tar balls;"
            " e.g prefix.v0.result-data.YYYY-MM-DD",
        },
        "result-data-sample": {
            "idxname": "result-data-sample",
            "template_name": "{prefix}.v{version}.{idxname}",
            "template_pat": "{prefix}.v{version}.{idxname}.*",
            "template": "{prefix}.v{version}.{idxname}.{year}-{month}-{day}",
            "owned": True,
            "desc": "Daily result data (any data generated by the"
            " benchmark) for all pbench result tar balls;"
            " e.g prefix.v0.result-data-sample.YYYY-MM-DD",
        },
        "run": {
            "idxname": "run-data",
            "template_name": "{prefix}.v{version}.{idxname}",
            "template_pat": "{prefix}.v{version}.{idxname}.*",
            "template": "{prefix}.v{version}.{idxname}.{year}-{month}",
            "owned": True,
            "desc": "Monthly pbench run metadata for index tar balls;"
            " contains directories, file names, and their size,"
            " permissions, etc.; e.g. prefix.v0.run.YYYY-MM",
        },
        "run-toc-entry": {
            "idxname": "run-toc",
            "template_name": "{prefix}.v{version}.{idxname}",
            "template_pat": "{prefix}.v{version}.{idxname}.*",
            "template": "{prefix}.v{version}.{idxname}.{year}-{month}",
            "owned": True,
            "desc": "Monthly table of contents metadata for index tar"
            " balls; contains directories, file names, and their size,"
            " permissions, etc.; e.g. prefix.v0.run.YYYY-MM",
        },
        "server-reports": {
            "idxname": "server-reports",
            "template_name": "{prefix}.v{version}.{idxname}",
            "template_pat": "{prefix}.v{version}.{idxname}.*",
            "template": "{prefix}.v{version}.{idxname}.{year}-{month}",
            "owned": False,
            "desc": "Monthly pbench server status reports for all"
            " cron jobs; e.g. prefix.v0.server-reports.YYYY-MM",
        },
        "tool-data": {
            "idxname": "tool-data-{tool}",
            "template_name": "{prefix}.v{version}.{idxname}",
            "template_pat": "{prefix}.v{version}.{idxname}.*",
            "template": "{prefix}.v{version}.{idxname}.{year}-{month}-{day}",
            "owned": True,
            "desc": "Daily tool data for all tools land in indices"
            " named by tool; e.g. prefix.v0.tool-data-iostat.YYYY-MM-DD",
        },
    }

    # REGEX pattern to pull the tool name out of the standard file name pattern
    # for tool mapping files. The "toolname" group becomes the internal name of
    # the template and the DB key.
    _fpat = re.compile(r"tool-data-frag-(?P<toolname>.+)\.json")

    def __init__(
        self,
        prefix: str = None,
        mappings: Path = None,
        settings: JsonFile = None,
        skeleton: JsonFile = None,
        tool: str = None,
    ):
        """
        Describe an Elasticsearch template including a JSON document mappings
        file and a JSON settings file, which will be merged into a full
        Elasticsearch template payload.

        A "skeleton" JSON file may also be linked, from which the mappings will
        be built by merging tool-specific properties and version into a common
        base template.

        Args:
            prefix: Pbench index prefix string
            mappings: JSON document description. Defaults to None.
            settings: JSON index settings. Defaults to None.
            skeleton: A versionless skeleton mappings file to merge with the tool
                mappings.
            tool: Tool mapping files stitch together mapping JSON from the
                main and skeleton templates using a parsed "tool" name.
        """
        self.prefix = prefix
        self.settings = settings
        if tool:
            self.mappings = JsonToolFile(mappings)
            self.key = tool
            m = self._fpat.match(mappings.name)
            self.name = m.group("toolname")
        else:
            self.mappings = JsonFile(mappings)
            self.name = mappings.stem
            self.key = self.name
        self.index_info = self.index_patterns[self.key]
        self.idxname = self.index_info["idxname"].format(tool=self.name)
        self.version = None
        self.tool = tool
        self.skeleton = skeleton
        if skeleton:
            self.modified = max(self.mappings.modified, self.skeleton.modified)
        else:
            self.modified = self.mappings.modified
        self.loaded = False

    def load(self):
        """
        Load the associated JSON files into memory; including both the "main"
        mapping file, the settings file, and, if specified, a "skeleton"
        mapping file which provides a common base for a set of tool mappings.

        Expand templates to create all the information necessary to register a
        document template with Elasticsearch.

        Once this method returns, the body() method can be called to return
        the full Elasticsearch JSON payload necessary to register a document
        template and its index pattern.
        """
        # Don't go further if we've already loaded and processed
        if self.loaded:
            return
        self.mappings.load()
        self.version = self.mappings.get_version()
        if self.skeleton:
            self.skeleton.load()
            self.mappings.merge(self.name, self.skeleton)
        self.settings.load()
        idxver = self.version
        ip = self.index_info
        self.template_name = ip["template_name"].format(
            prefix=self.prefix, version=idxver, idxname=self.idxname
        )
        self.index_pattern = ip["template_pat"].format(
            prefix=self.prefix, version=idxver, idxname=self.idxname
        )
        self.index_template = ip["template"]

        # Add a standard "authorization" sub-document into the document
        # template if this document type is "owned" by a Pbench user.
        if ip["owned"]:
            self.add_mapping(
                "authorization",
                {
                    "properties": {
                        "owner": {"type": "keyword"},
                        "access": {"type": "keyword"},
                    }
                },
            )
        self.loaded = True

    def add_mapping(self, name: str, body: Dict[AnyStr, Any]):
        """
        Add a template property sub-document to the mappings.

        Args:
            name: Property name
            body: Subdocument description

        Raises:
            KeyError: the loaded template body doesn't have the expected
                "properties" key.
        """
        self.mappings.add_mapping(name, body)

    def update(self, template: Template):
        """
        Update the template object from a database model object rather than
        loading and processing mapping and setting files from disk.

        Args:
            template: DB Template instance
        """
        self.modified = template.mtime
        self.version = template.version
        self.mappings = JsonFile.raw_json(template.mappings)
        self.settings = JsonFile.raw_json(template.settings)
        self.template_name = template.template_name
        self.index_pattern = template.template_pattern
        self.index_template = template.index_template
        self.idxname = template.idxname

    def resolve(self):
        """
        Check the on-disk template mapping files' modification dates against
        the templates DB. Only if the template's base index name doesn't exist
        in the DB, or if the DB object is older than the on-disk template do
        we load the mapping files from disk.
        """
        try:
            template = Template.find(self.name)
        except TemplateNotFound:
            template = None

        # If we found a match that's not older, use it
        if template and template.mtime >= self.modified:
            self.update(template)
            return

        # If the DB version is missing, or older than the on-disk JSON, we need
        # to fully resolve the mapping files. If we found an older DB object,
        # update it with the new data, otherwise we create a new Template object.
        self.load()
        if not template:
            template = Template(
                name=self.name,
                idxname=self.idxname,
                template_name=self.template_name,
                file=str(self.mappings.file),
                template_pattern=self.index_pattern,
                index_template=self.index_template,
                settings=self.settings.json,
                mappings=self.mappings.json,
                version=self.version,
            )
            template.add()
        else:
            template.version = self.version
            template.mappings = self.mappings.json
            template.settings = self.settings.json
            template.mtime = self.modified
            template.update()

    def generate_index_name(self, source, toolname=None):
        """
        Return a fully formed index name given its template, prefix, source
        data (for an @timestamp field) and an optional tool name.

        Args:

        Raises:
            TemplateError: A problem with the index template descriptor.
            BadDate: A problem decoding the date from the source document.

        Returns:
            The Elasticsearch index into which the source document will be indexed.
        """
        version = self.version
        idxname = self.idxname

        try:
            ts_val = source["@timestamp"]
        except KeyError:
            raise BadDate(f"missing @timestamp in a source document: {source!r}")
        except TypeError as e:
            raise JsonFileError(
                f"Failed to generate index name, {e}, source: {source!r}"
            )
        year, month, day = ts_val.split("T", 1)[0].split("-")[0:3]
        return self.index_template.format(
            prefix=self.prefix,
            version=version,
            idxname=idxname,
            year=year,
            month=month,
            day=day,
        )

    def body(self) -> Dict[AnyStr, Any]:
        """
        Return a JSON payload suitable to POST to Elasticsearch in order to
        register an indexed document template.

        Returns:
            Elasticsearch template payload
        """
        return dict(
            index_patterns=self.index_pattern,
            settings=self.settings.json,
            mappings=self.mappings.json,
        )


class PbenchTemplates:
    """
    Encapsulation of methods for loading / working with all the Pbench
    templates needed to define our Elasticsearch document schema.
    """

    def __init__(self, basepath, idx_prefix, logger, known_tool_handlers=None, _dbg=0):
        # Determine the location of the mapping and settings files. We expect
        # the "basepath" parameter to be the PbenchServerConfig BINDIR attr,
        # which will be something like /opt/pbench-server/bin
        base_dir = Path(basepath).parent / "lib"
        mapping_dir = base_dir / "mappings"
        # Where to find the settings
        setting_dir = base_dir / "settings"

        self.versions = {}
        self.templates = {}
        self.idx_prefix = idx_prefix
        self.logger = logger
        self.known_tool_handlers = known_tool_handlers
        self._dbg = _dbg
        self.counters = Counter()

        # Pbench report status mapping and settings.
        self.add_template(
            TemplateFile(
                prefix=idx_prefix,
                mappings=mapping_dir / "server-reports.json",
                settings=JsonFile(setting_dir / "server-reports.json"),
            )
        )

        run_settings = JsonFile(setting_dir / "run.json")
        for mapping_fn in mapping_dir.glob("run*.json"):
            self.add_template(
                TemplateFile(
                    prefix=idx_prefix,
                    mappings=mapping_dir / mapping_fn,
                    settings=run_settings,
                )
            )

        result_settings = JsonFile(setting_dir / "result-data.json")
        for mapping_fn in mapping_dir.glob("result-data*.json"):
            self.add_template(
                TemplateFile(
                    prefix=idx_prefix,
                    mappings=mapping_dir / mapping_fn,
                    settings=result_settings,
                )
            )

        skeleton = JsonFile(mapping_dir / "tool-data-skel.json")
        tool_settings = JsonFile(setting_dir / "tool-data.json")
        for mapping_fn in mapping_dir.glob("tool-data-frag-*.json"):
            self.add_template(
                TemplateFile(
                    prefix=idx_prefix,
                    mappings=mapping_dir / mapping_fn,
                    settings=tool_settings,
                    skeleton=skeleton,
                    tool="tool-data",
                )
            )
        self.resolve()

    def add_template(self, template: TemplateFile):
        """
        Add a template to the mapping dictionary by the proper key.

        Args:
            template: Template document
        """
        self.templates[template.idxname] = template

    def resolve(self):
        """
        Using the Template database table and the information gathered during
        PbenchTemplate construction, decide which templates we need to load
        and resolve from disk, and which we can load from the database.
        """
        for template in self.templates.values():
            template.resolve()

    def dump_idx_patterns(self):
        """
        List the registered index template patterns to the user.

        NOTE: This doesn't do a simple traversal of the templates dictionary
        in order to retain an output style identical to the previous, with the
        generic "tool-data" description appearing only once following the last
        tool data pattern.
        """
        patterns = TemplateFile.index_patterns
        pattern_names = [idx for idx in patterns]
        pattern_names.sort()
        for idx in pattern_names:
            if idx != "tool-data":
                idxname = patterns[idx]["idxname"]
                print(
                    patterns[idx]["template"].format(
                        prefix=self.idx_prefix,
                        version=self.templates[idxname].version,
                        idxname=idxname,
                        year="YYYY",
                        month="MM",
                        day="DD",
                    )
                )
            else:
                tool_names = [
                    tool
                    for tool in self.known_tool_handlers
                    if self.known_tool_handlers[tool] is not None
                ]
                tool_names.sort()
                for tool_name in tool_names:
                    idxname = patterns[idx]["idxname"].format(tool=tool_name)
                    print(
                        patterns[idx]["template"].format(
                            prefix=self.idx_prefix,
                            version=self.templates[idxname].version,
                            idxname=idxname,
                            year="YYYY",
                            month="MM",
                            day="DD",
                        )
                    )
            print("{}\n".format(patterns[idx]["desc"]))
        sys.stdout.flush()

    def dump_templates(self):
        """
        List all of the registered template documents
        """
        templates = {t.template_name: t for t in self.templates.values()}
        template_names = [name for name in templates]
        template_names.sort()
        for name in template_names:
            print(
                "\n\nTemplate: {}\n\n{}\n".format(
                    name, json.dumps(templates[name].body(), indent=4, sort_keys=True)
                )
            )
        sys.stdout.flush()

    def update_templates(self, es, target_name=None):
        """
        Register with Elasticsearch the set of index templates used by the
        Pbench server.
        """
        if target_name is not None:
            idxname = TemplateFile.index_patterns[target_name]["idxname"]
        else:
            idxname = None
        template_names = {t.template_name: t for t in self.templates.values()}
        names = list(template_names.keys())
        names.sort()
        successes = retries = 0
        beg = end = None
        for name in names:
            template = template_names[name]
            if idxname is not None and not target_name == template.idxname:
                # If we were asked to only load a given template name, skip
                # all non-matching templates.
                continue
            try:
                _beg, _end, _retries, _stat = pyesbulk.put_template(
                    es, name, "pbench-{}".format(template.name), template.body(),
                )
            except Exception as e:
                self.counters["put_template_failures"] += 1
                raise TemplateError(f"Tool {name} update failed: {e}")
            else:
                successes += 1
                if beg is None:
                    beg = _beg
                end = _end
                retries += _retries
        log_action = self.logger.warning if retries > 0 else self.logger.debug
        log_action(
            "done templates (start ts: {}, end ts: {}, duration: {:.2f}s,"
            " successes: {:d}, retries: {:d})",
            tstos(beg),
            tstos(end),
            end - beg,
            successes,
            retries,
        )

    def generate_index_name(self, template_name, source, toolname=None):
        """
        Return a fully formed index name given its template, prefix, source
        data (for an @timestamp field) and an optional tool name.
        """
        for t in self.templates.values():
            if t.key == template_name and (toolname is None or t.name == toolname):
                template = t
                break
        else:
            self.counters["invalid_template_name"] += 1
            raise Exception(
                "Invalid template name, '{}': {}".format(template_name, template_name)
            )

        try:
            return template.generate_index_name(source, toolname)
        except BadDate:
            self.counters["ts_missing_at_timestamp"] += 1
            raise
        except JsonFileError:
            self.counters["bad_source"] += 1
            raise
