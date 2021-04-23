import datetime
from pathlib import Path
from sqlalchemy import Column, Integer, String, event
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.sqltypes import DateTime, JSON

from pbench.server.database.database import Database


class TemplateError(Exception):
    """
    TemplateError This is a base class for errors reported by the
                Template class. It is never raised directly, but
                may be used in "except" clauses.
    """

    pass


class TemplateSqlError(TemplateError):
    """
    TemplateSqlError SQLAlchemy errors reported through Template operations.

    The exception will identify the base name of the template index,
    along with the operation being attempted; the __cause__ will specify the
    original SQLAlchemy exception.
    """

    def __init__(self, operation, name):
        self.operation = operation
        self.name = name

    def __str__(self):
        return f"Error {self.operation} index {self.name}"


class TemplateNotFound(TemplateError):
    """
    TemplateNotFound Attempt to find a Template that doesn't exist.
    """

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return f"No template {self.name}"


class TemplateDuplicate(TemplateError):
    """
    TemplateDuplicate Attempt to create a Template that already exists.
    """

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return f"Duplicate template {self.name}"


class Template(Database.Base):
    """
    Identify a Pbench Elasticsearch document template

    Columns:
        id              Generated unique ID of table row
        name            Base name of index (e.g., "run")
        template_name   The Elasticsearch template name
        file            The source JSON mapping file
        mtime           Template file modification timestamp
        index_template  The template for the Elasticsearch index name
        settings        The JSON settings payload
        mappings        The JSON mappings payload
        version         The template version metadata
    """

    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    template_name = Column(String(255), unique=True, nullable=False)
    file = Column(String(255), unique=False, nullable=False, default=None)
    mtime = Column(DateTime, unique=False, nullable=False)
    index_template = Column(String(255), unique=False, nullable=False)
    settings = Column(JSON, unique=False, nullable=False)
    mappings = Column(JSON, unique=False, nullable=False)
    version = Column(String(255), unique=False, nullable=False)

    @staticmethod
    def create(**kwargs) -> Database.Base:
        """
        create A simple factory method to construct a new Template object and
        add it to the database.

        Args:
            kwargs: any of the column names defined above

        Returns:
            A new Template object initialized with the keyword parameters.
        """
        try:
            template = Template(**kwargs)
            template.add()
        except Exception:
            Template.logger.exception("Failed create: {}", kwargs.get("name"))
            raise
        return template

    @staticmethod
    def find(name: str) -> Database.Base:
        """
        find Return a Template object with the specified base name. For
        example, find("run-data").

        Args:
            name: Base index name

        Raises:
            TemplateSqlError: problem interacting with Database
            TemplateNotFound: the specified template doesn't exist

        Returns:
            Template: a template object with the specified base name
        """
        # Make sure we have controller and name from path
        try:
            template = Database.db_session.query(Template).filter_by(name=name).first()
        except SQLAlchemyError as e:
            Template.logger.warning("Error looking for {}", name, str(e))
            raise TemplateSqlError("finding", name) from e

        if template is None:
            Template.logger.warning("{} not found", name)
            raise TemplateNotFound(name)
        return template

    def __str__(self):
        """
        __str__ Return a string representation of the template

        Returns:
            string: Representation of the template
        """
        return f"{self.name}: {self.index_template}"

    def add(self):
        """
        add Add the Template object to the database
        """
        try:
            Database.db_session.add(self)
            Database.db_session.commit()
        except IntegrityError:
            Template.logger.exception("Duplicate template {}", self.name)
            raise TemplateDuplicate(self.name)
        except Exception:
            self.logger.exception("Can't add {} to DB", str(self))
            Database.db_session.rollback()
            raise TemplateSqlError("adding", self.name)

    def update(self):
        """
        update Update the database row with the modified version of the
        Template object.
        """
        try:
            Database.db_session.commit()
        except Exception:
            self.logger.error("Can't update {} in DB", str(self))
            Database.db_session.rollback()
            raise TemplateSqlError("updating", self.name)


@event.listens_for(Template, "init")
def check_required(target, args, kwargs):
    """
    Listen for an init event on Template to capture the source file's
    modification timestamp.
    """
    if "mtime" not in kwargs:
        kwargs["mtime"] = datetime.datetime.fromtimestamp(
            Path(kwargs["file"]).stat().st_mtime
        )
