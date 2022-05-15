#! /usr/bin/env python

"""
Main function.
"""

import json
import locale
import logging
import signal
import sys
from collections import defaultdict
from enum import IntEnum
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple
from urllib.parse import ParseResult, urlparse

import black
import toml
import typer

from datamodel_code_generator import (
    DEFAULT_BASE_CLASS,
    Error,
    InputFileType,
    InvalidClassNameError,
    OpenAPIScope,
    enable_debug_message,
    generate,
)
from datamodel_code_generator.custom_types import StrictTypes
from datamodel_code_generator.format import (
    PythonVersion,
    black_find_project_root,
    is_supported_in_black,
)
from datamodel_code_generator.parser import LiteralType
from datamodel_code_generator.reference import is_url


class Exit(IntEnum):
    """Exit reasons."""

    OK = 0
    ERROR = 1
    KeyboardInterrupt = 2


def sig_int_handler(_: int, __: Any) -> None:  # pragma: no cover
    exit(Exit.OK)


signal.signal(signal.SIGINT, sig_int_handler)

DEFAULT_ENCODING = locale.getpreferredencoding()

__LOGGER__ = logging.getLogger("datamodel_code_generator")


root = black_find_project_root((Path().resolve(),))
pyproject_path = root / "pyproject.toml"
pyproject: Dict[str, Any]
if pyproject_path.is_file():
    pyproject = {
        k.replace('-', '_'): v
        for k, v in toml.load(str(pyproject_path))
        .get('tool', {})
        .get('datamodel-codegen', {})
        .items()
    }
else:
    pyproject = {}


app = typer.Typer()


@app.command()
def main(
    input: Path = typer.Option(
        pyproject.get("input", None),
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Input file/directory, otherwise read from stdin",
    ),
    url: Optional[str] = typer.Option(
        pyproject.get("url", None),
        help="Input file URL. `--input` is ignored when `--url` is used",
    ),
    http_headers: Optional[List[str]] = typer.Option(
        pyproject.get("http_headers", None),
        help='Set headers in HTTP requests to the remote host. (example: "Authorization: Basic dXNlcjpwYXNz")',
    ),
    http_ignore_tls: bool = typer.Option(
        pyproject.get("http_ignore_tls", False),
        help="Disable verification of the remote host's TLS certificate",
    ),
    input_file_type: InputFileType = typer.Option(
        pyproject.get("input_file_type", InputFileType.Auto.value),
        help='Input file type',
    ),
    openapi_scopes: List[OpenAPIScope] = typer.Option(
        pyproject.get("openapi_scopes", [OpenAPIScope.Schemas.value]),
        help='Input file type',
    ),
    output: Path = typer.Option(
        pyproject.get("output"),
        file_okay=True,
        dir_okay=True,
        resolve_path=True,
        writable=True,
        help='Output file',
    ),
    base_class: str = typer.Option(
        pyproject.get("base_class", DEFAULT_BASE_CLASS),
        help='Base Class',
    ),
    field_constraints: bool = typer.Option(
        pyproject.get("field_constraints", False),
        help='Use field constraints and not con* annotations',
    ),
    use_annotated: bool = typer.Option(
        pyproject.get("use_annotated", False),
        help='Use typing.Annotated for Field(). Also, `--field-constraints` option will be enabled.',
    ),
    use_non_positive_negative_number_constrained_types: bool = typer.Option(
        pyproject.get("use_non_positive_negative_number_constrained_types", False),
        help='Use the Non{Positive,Negative}{FloatInt} types instead of the corresponding con* constrained types.',
    ),
    field_extra_keys: List[str] = typer.Option(
        pyproject.get("field_extra_keys", []),
        help='Add extra keys to field parameters',
    ),
    field_include_all_keys: bool = typer.Option(
        pyproject.get("field_include_all_keys", False),
        help='Add all keys to field parameters',
    ),
    snake_case_field: bool = typer.Option(
        pyproject.get("snake_case_field", False),
        help='Change camel-case field name to snake-case',
    ),
    strip_default_none: bool = typer.Option(
        pyproject.get("strip_default_none", False),
        help='Strip default None on fields',
    ),
    disable_appending_item_suffix: bool = typer.Option(
        pyproject.get("disable_appending_item_suffix", False),
        help='Disable appending `Item` suffix to model name in an array',
    ),
    allow_population_by_field_name: bool = typer.Option(
        pyproject.get("allow_population_by_field_name", False),
        help='Allow population by field name',
    ),
    enable_faux_immutability: bool = typer.Option(
        pyproject.get("enable_faux_immutability", False),
        help='Enable faux immutability',
    ),
    use_default: bool = typer.Option(
        pyproject.get("use_default", False),
        help='Use default value even if a field is required',
    ),
    force_optional: bool = typer.Option(
        pyproject.get("force_optional", False),
        help='Force optional for required fields',
    ),
    strict_nullable: bool = typer.Option(
        pyproject.get("strict_nullable", False),
        help='Treat default field as a non-nullable field (Only OpenAPI)',
    ),
    strict_types: List[StrictTypes] = typer.Option(
        pyproject.get("strict_types", []),
        help='Use strict types',
    ),
    disable_timestamp: bool = typer.Option(
        pyproject.get("disable_timestamp", False),
        help='Disable timestamp on file headers',
    ),
    use_standard_collections: bool = typer.Option(
        pyproject.get("use_standard_collections", False),
        help='Use standard collections for type hinting (list, dict)',
    ),
    use_generic_container_types: bool = typer.Option(
        pyproject.get("use_generic_container_types", False),
        help='Use generic container types for type hinting (typing.Sequence, typing.Mapping). '
        'If `--use-standard-collections` option is set, then import from collections.abc instead of typing',
    ),
    use_schema_description: bool = typer.Option(
        pyproject.get("use_schema_description", False),
        help='Use schema description to populate class docstring',
    ),
    reuse_model: bool = typer.Option(
        pyproject.get("reuse_model", False),
        help='Re-use models on the field when a module has the model with the same content',
    ),
    enum_field_as_literal: Optional[LiteralType] = typer.Option(
        pyproject.get("enum_field_as_literal", None),
        help='Parse enum field as literal. all: all enum field type are Literal. one: field type is Literal when an enum has only one possible value',
    ),
    set_default_enum_member: bool = typer.Option(
        pyproject.get("set_default_enum_member", False),
        help='Set enum members as default values for enum field',
    ),
    empty_enum_field_name: str = typer.Option(
        pyproject.get("empty_enum_field_name", '_'),
        help='Set field name when enum value is empty',
    ),
    class_name: Optional[str] = typer.Option(
        pyproject.get("class_name", None),
        help='Set class name of root model',
    ),
    use_title_as_name: bool = typer.Option(
        pyproject.get("use_title_as_name", False),
        help='use titles as class names of models',
    ),
    custom_template_dir: Optional[Path] = typer.Option(
        pyproject.get("custom_template_dir", None),
        help='Custom template directory',
    ),
    extra_template_data: Optional[typer.FileText] = typer.Option(
        pyproject.get("extra_template_data", None),
        help='Extra template data',
    ),
    aliases: Optional[typer.FileText] = typer.Option(
        pyproject.get("aliases", None),
        help='Alias mapping file',
    ),
    target_python_version: PythonVersion = typer.Option(
        pyproject.get("target_python_version", PythonVersion.PY_37.value),
        help='target python version',
    ),
    wrap_string_literal: Optional[bool] = typer.Option(
        pyproject.get("wrap_string_literal", False),
        help='Wrap string literal by using black `experimental-string-processing` option (require black 20.8b0 or later)',
    ),
    validation: bool = typer.Option(
        pyproject.get("validation", False),
        help='Enable validation (Only OpenAPI)',
    ),
    encoding: str = typer.Option(
        pyproject.get("encoding", DEFAULT_ENCODING),
        help='The encoding of input and output',
    ),
    debug: bool = typer.Option(
        pyproject.get("debug", False),
        help='show debug message',
    ),
    version: bool = typer.Option(pyproject.get("version", False), help='show version'),
) -> Exit:
    """Main function."""

    if version:
        from datamodel_code_generator.version import version

        print(version)
        exit(0)

    url_parsed: Optional[ParseResult] = None
    if url is not None:
        if is_url(url):  # pragma: no cover
            url_parsed = urlparse(url)
        else:
            raise Error(
                f'This protocol doesn\'t support only http/https. --input={url}'
            )  # pragma: no cover

    if not is_supported_in_black(target_python_version):  # pragma: no cover
        print(
            f"Installed black doesn't support Python version {config.target_python_version.value}.\n"  # type: ignore
            f"You have to install a newer black.\n"
            f"Installed black version: {black.__version__}",
            file=sys.stderr,
        )
        return Exit.ERROR

    # Parse http_headers
    def parse_http_header(each_item: Any) -> Tuple[str, str]:
        try:
            field_name, field_value = each_item.split(':', maxsplit=1)
            return field_name, field_value.lstrip()
        except ValueError:
            raise Error(f'Invalid http header: {each_item!r}')

    http_headers_parsed: Optional[List[Tuple[str, str]]] = (
        [parse_http_header(header) for header in http_headers] if http_headers else None
    )

    # Validate `use_generic_container_types`
    if (
        use_generic_container_types
        and target_python_version == target_python_version.PY_36
    ):
        raise Error(
            f"`--use-generic-container-types` can not be used with `--target-python_version` {target_python_version.PY_36.value}.\n"  # type: ignore
            " The version will be not supported in a future version"
        )

    # Set `field_constraints` is `use_annotated` was specified
    if use_annotated:
        field_constraints = True

    if debug:  # pragma: no cover
        enable_debug_message()

    extra_template_data_loaded: Optional[DefaultDict[str, Dict[str, Any]]] = None
    if extra_template_data is not None:
        with extra_template_data as data:
            try:
                extra_template_data_loaded = json.load(
                    data, object_hook=lambda d: defaultdict(dict, **d)
                )
            except json.JSONDecodeError as e:
                print(f"Unable to load extra template data: {e}", file=sys.stderr)
                return Exit.ERROR

    aliases_loaded: Optional[DefaultDict[str, Dict[str, Any]]] = None
    if aliases is not None:
        with aliases as data:
            try:
                aliases_loaded = json.load(data)
            except json.JSONDecodeError as e:
                print(f"Unable to load alias mapping: {e}", file=sys.stderr)
                return Exit.ERROR
        if not isinstance(aliases_loaded, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in aliases_loaded.items()
        ):
            print(
                'Alias mapping must be a JSON string mapping (e.g. {"from": "to", ...})',
                file=sys.stderr,
            )
            return Exit.ERROR

    try:
        generate(
            input_=url_parsed or input or sys.stdin.read(),
            input_file_type=input_file_type,
            output=output,
            target_python_version=target_python_version,
            base_class=base_class,
            custom_template_dir=custom_template_dir,
            validation=validation,
            field_constraints=field_constraints,
            snake_case_field=snake_case_field,
            strip_default_none=strip_default_none,
            extra_template_data=extra_template_data_loaded,
            aliases=aliases_loaded,
            disable_timestamp=disable_timestamp,
            allow_population_by_field_name=allow_population_by_field_name,
            apply_default_values_for_required_fields=use_default,
            force_optional_for_required_fields=force_optional,
            class_name=class_name,
            use_standard_collections=use_standard_collections,
            use_schema_description=use_schema_description,
            reuse_model=reuse_model,
            encoding=encoding,
            enum_field_as_literal=enum_field_as_literal,
            set_default_enum_member=set_default_enum_member,
            strict_nullable=strict_nullable,
            use_generic_container_types=use_generic_container_types,
            enable_faux_immutability=enable_faux_immutability,
            disable_appending_item_suffix=disable_appending_item_suffix,
            strict_types=strict_types,
            empty_enum_field_name=empty_enum_field_name,
            field_extra_keys=set(field_extra_keys),
            field_include_all_keys=field_include_all_keys,
            openapi_scopes=openapi_scopes,
            wrap_string_literal=wrap_string_literal,
            use_title_as_name=use_title_as_name,
            http_headers=http_headers_parsed,
            http_ignore_tls=http_ignore_tls,
            use_annotated=use_annotated,
            use_non_positive_negative_number_constrained_types=use_non_positive_negative_number_constrained_types,
        )
    except Exception as e:
        __LOGGER__.exception("%s", e)
        if isinstance (e, InvalidClassNameError):
            raise Exception(f'{e} You have to set `--class-name` option') from e
        raise


if __name__ == '__main__':
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    __LOGGER__.setLevel(logging.INFO)
    __LOGGER__.addHandler(handler)

    app()
