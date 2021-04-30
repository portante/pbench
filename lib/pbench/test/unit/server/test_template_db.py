import datetime
import pytest

from pbench.server.database.models.template import (
    Template,
    TemplateNotFound,
)


class TestTemplate:
    def test_construct(self, fake_mtime, db_session):
        """ Test dataset contructor
        """
        template = Template(
            name="run",
            idxname="run-data",
            template_name="tname",
            file="run.json",
            template_pattern="drb.v1.run.*",
            index_template="drb.v1.run.{year}-{month}",
            settings={"none": False},
            mappings={"properties": None},
            version=5,
        )
        template.add()
        assert template.name == "run"
        assert template.mtime == datetime.datetime(2021, 1, 29, 0, 0, 0)
        assert "run: drb.v1.run.{year}-{month}" == str(template)

    def test_find_exists(self, fake_mtime, db_session):
        """ Test that we can find a template
        """
        template1 = Template(
            name="run",
            idxname="run-data",
            template_name="run",
            file="run-toc.json",
            template_pattern="drb.v2.run-toc.*",
            index_template="drb.v2.run-toc.{year}-{month}",
            settings={"none": False},
            mappings={"properties": None},
            version=5,
        )
        template1.add()

        template2 = Template.find(name="run")
        assert template2.name == template1.name
        assert template2.id is template1.id

    def test_find_none(self, fake_mtime, db_session):
        """ Test expected failure when we try to find a template that
        does not exist.
        """
        with pytest.raises(TemplateNotFound):
            Template.find(name="data")
