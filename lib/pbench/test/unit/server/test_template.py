import datetime
import os
from pathlib import Path
from posix import stat_result
from stat import ST_MTIME
import pytest

from pbench.server.database.models.template import (
    Template,
    TemplateNotFound,
)


@pytest.fixture(autouse=True)
def fake_mtime(monkeypatch):
    """
    Template's init event listener provides the file's modification date to
    support template version control. For unit testing, mock the stat results
    to appear at a fixed time.

    Args:
        monkeypatch ([type]): [description]
    """

    def fake_stat(file: str):
        """
        Create a real stat_result using an actual file, but change the st_mtime
        to a known value before returning it.

        Args:
            file: filename (not used)

        Returns:
            mocked stat_results
        """
        s = os.stat(".")
        t = int(datetime.datetime(2021, 1, 29, 0, 0, 0).timestamp())
        f = list(s)
        f[ST_MTIME] = t
        return stat_result(f)

    with monkeypatch.context() as m:
        m.setattr(Path, "stat", fake_stat)
        yield


class TestTemplate:
    def test_construct(self):
        """ Test dataset contructor
        """
        template = Template(
            name="run",
            template_name="tname",
            file="run.json",
            index_template="run.{year}-{month}",
            settings={"none": False},
            mappings={"properties": None},
            version=5,
        )
        template.add()
        assert template.name == "run"
        assert template.mtime == datetime.datetime(2021, 1, 29, 0, 0, 0)
        assert "run: run.{year}-{month}" == str(template)

    def test_find_exists(self):
        """ Test that we can find a template
        """
        template1 = Template(
            name="run-toc",
            template_name="toc",
            file="run-toc.json",
            index_template="run-toc.{year}-{month}",
            settings={"none": False},
            mappings={"properties": None},
            version=5,
        )
        template1.add()

        template2 = Template.find(name="run-toc")
        assert template2.name == template1.name
        assert template2.id is template1.id

    def test_find_none(self):
        """ Test expected failure when we try to find a template that
        does not exist.
        """
        with pytest.raises(TemplateNotFound):
            Template.find(name="data")
