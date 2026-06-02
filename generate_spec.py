#!/usr/bin/env python3
import os
import sys
import json
import argparse
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# Default credentials from environment or placeholder defaults
DEFAULT_HOST = os.environ.get("PEXIP_HOST", "your-pexip-manager.example.com")
DEFAULT_USER = os.environ.get("PEXIP_USER", "admin")
DEFAULT_PASS = os.environ.get("PEXIP_PASSWORD", "")


def map_tastypie_type(tp_type):
    """Maps Tastypie types to OpenAPI types."""
    mapping = {
        "string": {"type": "string"},
        "integer": {"type": "integer"},
        "boolean": {"type": "boolean"},
        "float": {"type": "number"},
        "decimal": {"type": "number"},
        "datetime": {"type": "string", "format": "date-time"},
        "date": {"type": "string", "format": "date"},
        "related": {
            "type": "string",
            "description": "Foreign key reference URI to the related resource.",
        },
        "dict": {"type": "object"},
        "list": {"type": "array", "items": {"type": "string"}},
    }
    return mapping.get(tp_type, {"type": "string"})


def get_openapi_base(host):
    """Returns the base OpenAPI skeleton."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Pexip Infinity REST API",
            "version": "v40",
            "description": "Auto-generated OpenAPI 3.0 specification for Pexip Infinity Management Node, compiled directly from the dynamic schema registry.",
            "contact": {"name": "Pexip Community Tools"},
        },
        "servers": [{"url": f"https://{host}"}],
        "paths": {},
        "components": {
            "securitySchemes": {"basicAuth": {"type": "http", "scheme": "basic"}},
            "schemas": {},
        },
        "security": [{"basicAuth": []}],
    }


def parse_resource_schema(resource_name, group, schema_data, openapi_spec):
    """Translates a Tastypie resource schema definition into OpenAPI paths and components."""
    base_endpoint = f"/api/admin/{group}/v1/{resource_name}/"
    detail_endpoint = f"/api/admin/{group}/v1/{resource_name}/{{id}}/"

    fields = schema_data.get("fields", {})
    allowed_list_methods = schema_data.get("allowed_list_http_methods", ["get"])
    allowed_detail_methods = schema_data.get("allowed_detail_http_methods", ["get"])

    # 1. Build Schema Definition
    properties = {}
    required_fields = []

    for field_name, field_info in fields.items():
        if field_name == "resource_uri":
            properties[field_name] = {
                "type": "string",
                "readOnly": True,
                "description": "The unique resource URI.",
            }
            continue

        tp_type = field_info.get("type", "string")
        oas_prop = map_tastypie_type(tp_type)

        # Add help text/description
        help_text = field_info.get("help_text")
        if help_text:
            oas_prop["description"] = help_text

        # Handle read-only
        if field_info.get("readonly", False):
            oas_prop["readOnly"] = True

        # Handle nullable / required (only for non-readonly fields)
        if not field_info.get("readonly", False):
            if (
                not field_info.get("nullable", True)
                and field_info.get("default") == "No default"
            ):
                required_fields.append(field_name)

        # Handle default values
        default_val = field_info.get("default")
        if default_val is not None and default_val != "No default":
            # Strip simple string defaults if needed
            if isinstance(default_val, str) and (
                default_val.startswith("'") or default_val.startswith('"')
            ):
                default_val = default_val.strip("'\"")
            oas_prop["default"] = default_val

        # Handle enums / choices
        choices = field_info.get("choices")
        if choices:
            # Tastypie choices are often lists of [value, display_name]
            oas_prop["enum"] = [c[0] if isinstance(c, list) else c for c in choices]

        properties[field_name] = oas_prop

    schema_name = f"{group.capitalize()}_{resource_name}"
    schema_def = {"type": "object", "properties": properties}
    if required_fields:
        schema_def["required"] = required_fields

    openapi_spec["components"]["schemas"][schema_name] = schema_def

    # Add standard listing response wrapper
    list_response_name = f"{schema_name}_List"
    openapi_spec["components"]["schemas"][list_response_name] = {
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                    "offset": {"type": "integer", "default": 0},
                    "total_count": {"type": "integer"},
                    "next": {"type": "string", "nullable": True},
                    "previous": {"type": "string", "nullable": True},
                },
            },
            "objects": {
                "type": "array",
                "items": {"$ref": f"#/components/schemas/{schema_name}"},
            },
        },
    }

    # 2. Build Paths
    # List endpoint
    list_paths = {}
    if "get" in allowed_list_methods:
        # Build query parameters from filtering metadata
        parameters = [
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "default": 20},
                "description": "Number of records to return.",
            },
            {
                "name": "offset",
                "in": "query",
                "schema": {"type": "integer", "default": 0},
                "description": "Offset index for pagination.",
            },
        ]

        filtering = schema_data.get("filtering", {})
        for filter_field, filter_types in filtering.items():
            # Tastypie uses integer constants (e.g., 1 = ALL, 2 = ALL_WITH_RELATIONS) in some schemas
            if isinstance(filter_types, int):
                lookups = ["exact"]
            elif isinstance(filter_types, list):
                lookups = filter_types
            else:
                lookups = ["exact"]

            for f_type in lookups:
                param_name = filter_field
                if f_type != "exact":
                    param_name = f"{filter_field}__{f_type}"

                parameters.append(
                    {
                        "name": param_name,
                        "in": "query",
                        "schema": {"type": "string"},
                        "description": f"Filter records where '{filter_field}' matches '{f_type}' criteria.",
                    }
                )

        list_paths["get"] = {
            "summary": f"List {resource_name} ({group})",
            "description": (
                f"Retrieve a list of `{resource_name}` records from the Pexip Management Node config/status registry.\n\n"
                "### Prerequisites\n"
                "- **Authentication**: HTTP Basic Auth or OAuth2 Bearer Token (signed with ES256).\n\n"
                "### Scopes\n"
                f"- `admin:read:{group}`\n\n"
                "### Rate Limit Label\n"
                "- **MEDIUM**"
            ),
            "tags": [group],
            "parameters": parameters,
            "responses": {
                "200": {
                    "description": "Successful retrieval of records.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": f"#/components/schemas/{list_response_name}"
                            }
                        }
                    },
                }
            },
        }

    if "post" in allowed_list_methods:
        list_paths["post"] = {
            "summary": f"Create {resource_name} ({group})",
            "description": (
                f"Create a new `{resource_name}` record on the Pexip Management Node.\n\n"
                "### Prerequisites\n"
                "- **Authentication**: HTTP Basic Auth or OAuth2 Bearer Token (signed with ES256).\n\n"
                "### Scopes\n"
                f"- `admin:write:{group}`\n\n"
                "### Rate Limit Label\n"
                "- **MEDIUM**"
            ),
            "tags": [group],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                    }
                },
            },
            "responses": {
                "201": {
                    "description": "Created successfully. Check the 'Location' response header for the URI.",
                    "headers": {
                        "Location": {
                            "schema": {"type": "string"},
                            "description": "URI of the newly created resource.",
                        }
                    },
                },
                "400": {"description": "Validation or field constraint error."},
            },
        }

    if list_paths:
        openapi_spec["paths"][base_endpoint] = list_paths

    # Detail endpoint
    detail_paths = {}
    path_parameters = [
        {
            "name": "id",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "description": "The unique resource identifier.",
        }
    ]

    if "get" in allowed_detail_methods:
        detail_paths["get"] = {
            "summary": f"Get {resource_name} by ID ({group})",
            "description": (
                f"Retrieve detailed fields for a single `{resource_name}` record by its unique identifier.\n\n"
                "### Prerequisites\n"
                "- **Authentication**: HTTP Basic Auth or OAuth2 Bearer Token (signed with ES256).\n\n"
                "### Scopes\n"
                f"- `admin:read:{group}`\n\n"
                "### Rate Limit Label\n"
                "- **MEDIUM**"
            ),
            "tags": [group],
            "parameters": path_parameters,
            "responses": {
                "200": {
                    "description": "Successful retrieval.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                        }
                    },
                },
                "404": {"description": "Resource not found."},
            },
        }

    if "patch" in allowed_detail_methods:
        detail_paths["patch"] = {
            "summary": f"Update {resource_name} ({group})",
            "description": (
                f"Modify specific properties of an existing `{resource_name}` record on the Pexip Management Node.\n\n"
                "### Prerequisites\n"
                "- **Authentication**: HTTP Basic Auth or OAuth2 Bearer Token (signed with ES256).\n\n"
                "### Scopes\n"
                f"- `admin:write:{group}`\n\n"
                "### Rate Limit Label\n"
                "- **MEDIUM**"
            ),
            "tags": [group],
            "parameters": path_parameters,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                    }
                },
            },
            "responses": {
                "202": {"description": "Update accepted."},
                "204": {"description": "No content. Update completed."},
                "400": {"description": "Validation error."},
                "404": {"description": "Resource not found."},
            },
        }

    if "delete" in allowed_detail_methods:
        detail_paths["delete"] = {
            "summary": f"Delete {resource_name} ({group})",
            "description": (
                f"Remove an existing `{resource_name}` record from the Pexip Management Node config/status registry.\n\n"
                "### Prerequisites\n"
                "- **Authentication**: HTTP Basic Auth or OAuth2 Bearer Token (signed with ES256).\n\n"
                "### Scopes\n"
                f"- `admin:write:{group}`\n\n"
                "### Rate Limit Label\n"
                "- **MEDIUM**"
            ),
            "tags": [group],
            "parameters": path_parameters,
            "responses": {
                "204": {"description": "Deleted successfully."},
                "404": {"description": "Resource not found."},
            },
        }

    if detail_paths:
        openapi_spec["paths"][detail_endpoint] = detail_paths


def get_command_endpoints():
    """Returns the hard-coded command paths since Tastypie Command API is POST-only and has no list endpoint."""
    commands = {
        "/api/admin/command/v1/participant/dial/": {
            "summary": "Dial participant into conference",
            "description": "Add a remote participant (e.g. SIP/H.323 room or streaming/recording RTMP endpoint) into an active VMR.",
            "properties": {
                "conference_alias": {
                    "type": "string",
                    "description": "Target VMR alias to dial into.",
                },
                "destination": {
                    "type": "string",
                    "description": "SIP/H.323 destination address to dial out to.",
                },
                "routing": {
                    "type": "string",
                    "enum": ["routing_rule", "manual"],
                    "default": "routing_rule",
                    "description": "Routing mode for the dial request.",
                },
                "protocol": {
                    "type": "string",
                    "enum": [
                        "sip",
                        "h323",
                        "mssip",
                        "rtmp",
                        "teams",
                        "gms",
                        "auto",
                    ],
                    "default": "auto",
                },
                "role": {
                    "type": "string",
                    "enum": ["chair", "guest"],
                    "default": "guest",
                },
                "system_location": {
                    "type": "string",
                    "description": "Location name to originate the dial-out from.",
                },
                "node": {
                    "type": "string",
                    "description": "IP address of Conferencing Node (used if routing is manual).",
                },
                "remote_display_name": {
                    "type": "string",
                    "description": "Remote display name for the dialed participant.",
                },
            },
        },
        "/api/admin/command/v1/participant/disconnect/": {
            "summary": "Disconnect participant",
            "description": "Disconnect an existing participant from a conference instance.",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "UUID of the participant to boot.",
                }
            },
        },
        "/api/admin/command/v1/conference/disconnect/": {
            "summary": "Disconnect conference",
            "description": "Disconnect all participants and terminate the conference instance.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "Conference UUID to disconnect.",
                }
            },
        },
        "/api/admin/command/v1/participant/mute/": {
            "summary": "Mute participant",
            "description": "Mute the audio being sent from a participant so others cannot hear them.",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "UUID of the participant to mute.",
                }
            },
        },
        "/api/admin/command/v1/conference/mute_guests/": {
            "summary": "Mute all Guests",
            "description": "Mute the audio being received from all Guest participants in a conference.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "UUID of the conference.",
                }
            },
        },
        "/api/admin/command/v1/participant/unmute/": {
            "summary": "Unmute participant",
            "description": "Restore audio for a previously muted participant.",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "UUID of the participant to unmute.",
                }
            },
        },
        "/api/admin/command/v1/conference/unmute_guests/": {
            "summary": "Unmute all Guests",
            "description": "Unmute the audio being received from all Guest participants in a conference.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "UUID of the conference.",
                }
            },
        },
        "/api/admin/command/v1/conference/lock/": {
            "summary": "Lock conference",
            "description": "Lock the conference VMR to prevent new participants from joining immediately (holds them in lobby).",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "UUID of the conference to lock.",
                }
            },
        },
        "/api/admin/command/v1/conference/unlock/": {
            "summary": "Unlock conference",
            "description": "Unlock a locked conference, allowing waiting lobby participants to join.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "UUID of the conference to unlock.",
                }
            },
        },
        "/api/admin/command/v1/participant/unlock/": {
            "summary": "Unlock participant",
            "description": "Allow a participant waiting in the lobby/host screen to join the conference.",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "UUID of the participant to unlock.",
                }
            },
        },
        "/api/admin/command/v1/participant/transfer/": {
            "summary": "Transfer participant",
            "description": "Move a participant from one conference to another.",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "UUID of the participant to transfer.",
                },
                "conference_alias": {
                    "type": "string",
                    "description": "Destination VMR alias.",
                },
                "role": {
                    "type": "string",
                    "enum": ["chair", "guest"],
                    "default": "guest",
                },
            },
        },
        "/api/admin/command/v1/participant/role/": {
            "summary": "Change participant role",
            "description": "Change a participant's role to Guest or Chair.",
            "properties": {
                "participant_id": {
                    "type": "string",
                    "description": "UUID of the participant.",
                },
                "role": {
                    "type": "string",
                    "enum": ["chair", "guest"],
                    "default": "guest",
                },
            },
        },
        "/api/admin/command/v1/conference/transform_layout/": {
            "summary": "Transform layout",
            "description": "Dynamically change the layout, overlay text, and other indicators in the conference.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "UUID of the conference.",
                },
                "enable_overlay_text": {
                    "type": "boolean",
                    "default": True,
                },
                "layout": {
                    "type": "string",
                    "description": "Layout code, e.g. '4:0', 'nine_equal', etc.",
                    "default": "4:0",
                },
            },
        },
        "/api/admin/command/v1/platform/backup_create/": {
            "summary": "Create backup",
            "description": "Create a system configuration backup encrypted with a passphrase.",
            "properties": {
                "passphrase": {
                    "type": "string",
                    "description": "Passphrase used to encrypt the backup.",
                },
                "request": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set to true to run in the background and receive a status URI.",
                },
            },
        },
        "/api/admin/command/v1/platform/backup_restore/": {
            "summary": "Restore backup",
            "description": "Restore a system configuration backup using an uploaded archive and passphrase.",
            "properties": {
                "passphrase": {
                    "type": "string",
                    "description": "Passphrase used to encrypt the backup package.",
                },
                "package": {
                    "type": "string",
                    "description": "Binary backup file package payload.",
                },
            },
        },
        "/api/admin/command/v1/conference/sync/": {
            "summary": "Sync LDAP template",
            "description": "Manually trigger LDAP template synchronization.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "Optional conference UUID to sync.",
                }
            },
        },
        "/api/admin/command/v1/conference/send_conference_email/": {
            "summary": "Send provisioning email to VMR owner",
            "description": "Send a provisioning email containing VMR details to its owner.",
            "properties": {
                "conference_id": {
                    "type": "string",
                    "description": "UUID of the conference.",
                }
            },
        },
        "/api/admin/command/v1/conference/send_device_email/": {
            "summary": "Send provisioning email to device owner",
            "description": "Send a provisioning email to a device owner.",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "UUID of the device configuration.",
                }
            },
        },
        "/api/admin/command/v1/platform/certificates_import/": {
            "summary": "Certificate upload",
            "description": "Upload a platform SSL/TLS certificate.",
            "properties": {
                "certificate": {
                    "type": "string",
                    "description": "PEM certificate content.",
                },
                "private_key": {
                    "type": "string",
                    "description": "PEM private key content.",
                },
            },
        },
        "/api/admin/command/v1/platform/start_cloudnode/": {
            "summary": "Start an overflow Conferencing Node",
            "description": "Manually start a specific stopped overflow/bursting Conferencing Node.",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Instance ID of the cloud overflow node.",
                }
            },
        },
        "/api/admin/command/v1/platform/snapshot/": {
            "summary": "Take system snapshot",
            "description": "Take a diagnostic snapshot of the system history (e.g. past 12 hours).",
            "properties": {
                "limit": {
                    "type": "integer",
                    "default": 12,
                    "description": "Number of hours of history to capture.",
                },
                "request": {
                    "type": "boolean",
                    "default": False,
                    "description": "Set to true to run in the background and receive a status URI.",
                },
            },
        },
        "/api/admin/command/v1/platform/upgrade/": {
            "summary": "Platform upgrade",
            "description": "Trigger a platform software upgrade.",
            "properties": {
                "version": {
                    "type": "string",
                    "description": "Software version bundle name to upgrade to.",
                }
            },
        },
        "/api/admin/command/v1/platform/software_bundle/": {
            "summary": "Upload software bundle",
            "description": "Upload a Pexip software upgrade bundle to the Management Node.",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Binary upgrade bundle payload.",
                }
            },
        },
    }
    return commands


def main():
    parser = argparse.ArgumentParser(description="Pexip OpenAPI 3.0 Generator")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="IP or FQDN of the Pexip Management Node",
    )
    parser.add_argument(
        "--user", default=DEFAULT_USER, help="Admin username (default: admin)"
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASS,
        help="Admin password for Pexip Management Node",
    )
    parser.add_argument(
        "--output", default="openapi.json", help="Path to write openapi.json"
    )
    parser.add_argument(
        "--raw-list",
        default="/Users/joshestrada/.gemini/antigravity-ide/brain/40e9acd5-22fc-4ae3-b610-f92bdb822ab5/scratch/endpoints_raw.json",
        help="Path to endpoints_raw.json list",
    )
    args = parser.parse_args()

    # Load resources
    if not os.path.exists(args.raw_list):
        print(f"[ERROR] Registry file not found at {args.raw_list}")
        sys.exit(1)

    with open(args.raw_list, "r") as f:
        registry = json.load(f)

    openapi_spec = get_openapi_base(args.host)
    session = requests.Session()
    session.auth = (args.user, args.password)
    session.headers.update(
        {"Content-Type": "application/json", "Accept": "application/json"}
    )

    # Compile endpoints
    for group in ["configuration", "status", "history"]:
        resources = registry.get(group, {})
        print(
            f"Generating paths for API group '{group}' ({len(resources)} resources)..."
        )

        for resource_name, endpoints_info in resources.items():
            schema_path = endpoints_info.get("schema")
            if not schema_path:
                continue

            schema_url = f"https://{args.host}{schema_path}?format=json"
            print(f"  - Fetching schema for {group}/{resource_name}...")

            try:
                resp = session.get(schema_url, verify=False, timeout=10)
                if resp.status_code == 200:
                    schema_data = resp.json()
                    parse_resource_schema(
                        resource_name, group, schema_data, openapi_spec
                    )
                else:
                    print(
                        f"    [WARN] Failed to fetch schema (HTTP {resp.status_code}) for {resource_name}"
                    )
            except Exception as e:
                print(f"    [WARN] Connection error for {resource_name}: {e}")

    # Process Command API
    print("Generating hardcoded Command API paths...")
    command_paths = get_command_endpoints()
    for path, cmd_info in command_paths.items():
        schema_name = f"Command_{path.split('/')[-2]}"
        openapi_spec["components"]["schemas"][schema_name] = {
            "type": "object",
            "properties": cmd_info["properties"],
        }

        summary = cmd_info["summary"]
        base_desc = cmd_info.get(
            "description",
            f"Executes the `{summary}` command on the Pexip Management Node.",
        )
        enriched_desc = (
            f"{base_desc}\n\n"
            "### Prerequisites\n"
            "- **Authentication**: HTTP Basic Auth or OAuth2 Bearer Token (signed with ES256).\n"
            "- **Session**: Active live conference / participant session (if ID is required).\n\n"
            "### Scopes\n"
            "- `admin:command`\n\n"
            "### Rate Limit Label\n"
            "- **MEDIUM**"
        )

        openapi_spec["paths"][path] = {
            "post": {
                "summary": summary,
                "description": enriched_desc,
                "tags": ["command"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string"},
                                        "data": {"type": "object"},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Invalid parameter request body."},
                    "404": {"description": "Meeting/Participant not found."},
                },
            }
        }

    # Write output file
    print(f"Writing complete OpenAPI 3.0 specification to '{args.output}'...")
    with open(args.output, "w") as f:
        json.dump(openapi_spec, f, indent=2)

    print("[SUCCESS] Specification compilation complete.")


if __name__ == "__main__":
    main()
