#!/usr/bin/env python3
import json
import os
import urllib.request

openapi_path = "openapi.json"
output_path = "pexip_postman_collection.json"

if not os.path.exists(openapi_path):
    print(f"[ERROR] {openapi_path} not found. Run generate_spec.py first.")
    exit(1)

with open(openapi_path, "r") as f:
    spec = json.load(f)

# Fetch postman-util-lib bundle to pre-populate pmlib_code
print("Fetching postman-util-lib bundle...")
pmlib_bundle_code = ""
try:
    with urllib.request.urlopen(
        "https://joolfe.github.io/postman-util-lib/dist/bundle.js", timeout=10
    ) as response:
        pmlib_bundle_code = response.read().decode("utf-8")
    print("[SUCCESS] postman-util-lib bundle downloaded successfully.")
except Exception as e:
    print(
        f"[WARN] Could not fetch postman-util-lib: {e}. 'pmlib_code' variable will be empty."
    )

# Extract default host — use a generic placeholder for the public collection
servers = spec.get("servers", [])
default_host = "https://your-pexip-manager.example.com"

# Base Postman Collection structure
oauth_pre_request_script = [
    "// Auto-detect auth method based on which credentials the user has configured",
    "const mgmt = pm.collectionVariables.get('baseUrl') || pm.environment.get('baseUrl') || pm.environment.get('host');",
    "const clientId = pm.collectionVariables.get('client_id') || pm.environment.get('client_id');",
    "const clientPrivateKey = pm.collectionVariables.get('client_private_key') || pm.environment.get('client_private_key');",
    "",
    "if (clientId && clientPrivateKey && mgmt) {",
    "    const pmlibCode = pm.collectionVariables.get('pmlib_code') || pm.environment.get('pmlib_code') || pm.globals.get('pmlib_code');",
    "    if (!pmlibCode) {",
    "        console.warn(\"OAuth2 configuration detected, but 'pmlib_code' is not set.\");",
    "    } else {",
    "        try {",
    "            // Load the crypto utility library",
    "            eval(pmlibCode);",
    "",
    "            const timestampCurrent = Math.floor(Date.now() / 1000);",
    "            const tokenExpiry = pm.collectionVariables.get('expires') || pm.environment.get('expires') || 0;",
    "            const cachedToken = pm.collectionVariables.get('access_token') || pm.environment.get('access_token');",
    "",
    "            // Check if the current token is still valid (with a 10-second buffer)",
    "            if (cachedToken && (tokenExpiry - timestampCurrent > 10)) {",
    "                console.log('OAuth2 Bearer token is still valid.');",
    "                pm.request.headers.upsert({ key: 'Authorization', value: 'Bearer ' + cachedToken });",
    "            } else {",
    "                console.log('OAuth2 Bearer token expired or missing, requesting new token...');",
    "                ",
    "                // Clean host URL to ensure correct audience format",
    "                const cleanHost = mgmt.replace(/^https?:\\/\\//, '').split('/')[0];",
    "                const audience = `https://${cleanHost}/oauth/token/`;",
    "",
    "                // Sign JWT assertion using postman-util-lib helper (ES256 signed client assertion)",
    "                const signedJWS = pmlib.clientAssertPrivateKey(clientPrivateKey, clientId, audience, 3600, 'ES256');",
    "",
    "                pm.sendRequest({",
    "                    url: audience,",
    "                    method: 'POST',",
    "                    header: {",
    "                        'Content-Type': 'application/x-www-form-urlencoded',",
    "                        'Authorization': ''",
    "                    },",
    "                    body: {",
    "                        mode: 'urlencoded',",
    "                        urlencoded: [",
    "                            { key: 'grant_type', value: 'client_credentials' },",
    "                            { key: 'client_assertion_type', value: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer' },",
    "                            { key: 'client_assertion', value: signedJWS },",
    "                            { key: 'scope', value: 'is_admin use_api' }",
    "                        ]",
    "                    }",
    "                }, (error, response) => {",
    "                    if (!error && response.code === 200) {",
    "                        const jsonData = response.json();",
    "                        pm.collectionVariables.set('access_token', jsonData.access_token);",
    "                        pm.collectionVariables.set('expires', timestampCurrent + 3600);",
    "                        pm.request.headers.upsert({ key: 'Authorization', value: 'Bearer ' + jsonData.access_token });",
    "                        console.log('OAuth2 Bearer token refreshed and injected successfully.');",
    "                    } else {",
    "                        console.error('Failed to fetch OAuth2 token:', error || (response ? response.json() : 'No response'));",
    "                    }",
    "                });",
    "            }",
    "        } catch (e) {",
    '            console.error("Error executing OAuth2 Pre-request script: ", e);',
    "        }",
    "    }",
    "} else {",
    "    // No OAuth2 credentials — fall back to Basic Auth",
    "    const username = pm.environment.get('pexip_admin_username') || pm.collectionVariables.get('pexip_admin_username') || 'admin';",
    "    const password = pm.environment.get('pexip_admin_password') || pm.collectionVariables.get('pexip_admin_password') || '';",
    "    const rawCredentials = username + ':' + password;",
    "    const wordArr = CryptoJS.enc.Utf8.parse(rawCredentials);",
    "    const base64Credentials = CryptoJS.enc.Base64.stringify(wordArr);",
    "    pm.request.headers.upsert({ key: 'Authorization', value: 'Basic ' + base64Credentials });",
    "}",
]

collection = {
    "info": {
        "name": "Pexip Infinity REST API",
        "description": 'Auto-compiled Postman Collection for Pexip Infinity. Includes pre-configured Basic Authentication, environment variables, request chaining, and built-in OAuth2 support.\n\nAuthentication is auto-detected by the pre-request script — just fill in your credentials and the correct auth method is used automatically.\n\n### How to Configure Authentication\n\n#### Option A: Basic Authentication (Default)\n1. Select your active Postman Environment (**Pexip Infinity REST API Environment**).\n2. Set `baseUrl` and `pexip_admin_password` (the password will be masked automatically).\n3. Send any request — Basic Auth is used automatically when no OAuth2 credentials are set.\n\n#### Option B: OAuth2 Authentication (Recommended)\nTo configure OAuth2, you must obtain client credentials from Pexip:\n1. Log in to your **Pexip Infinity Management Node**.\n2. Navigate to **Users & Devices > OAuth2 Clients** and select **Add OAuth2 client**.\n3. Enter a **Client name**, assign the desired **Role**, and click **Save**.\n4. **Important**: Copy the generated **Client ID** and **Private key** (the private key is only displayed once).\n5. In your active Postman Environment, set:\n   - `client_id` = `<your_client_id>`\n   - `client_private_key` = `<your_private_key>` (displays masked)\n6. Send any request — the pre-request script will automatically detect your OAuth2 credentials, sign the JWT assertion, fetch a Bearer token, and switch the auth method. No manual configuration of the Authorization tab is needed.\n\n### Troubleshooting / SSL Verification\nIf your request fails immediately with **"Could not get any response"**:\n- Pexip Management Nodes often use self-signed SSL certificates.\n- **To resolve**: Open Postman **Settings** (gear icon in the top right) -> **General** tab -> toggle **SSL certificate verification** to **OFF**.',
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [],
    "variable": [
        {"key": "active_conference_id", "value": "", "type": "string"},
        {"key": "active_conference_name", "value": "", "type": "string"},
        {"key": "active_participant_id", "value": "", "type": "string"},
        {"key": "access_token", "value": "", "type": "secret"},
        {"key": "expires", "value": "", "type": "string"},
    ],
    "auth": {"type": "noauth"},
    "event": [
        {
            "listen": "prerequest",
            "script": {"type": "text/javascript", "exec": oauth_pre_request_script},
        }
    ],
}

# Folder descriptions for the collection
folder_descriptions = {
    "configuration": "Endpoints for managing persistent system configurations (like adding users, editing locations, setting up NTP servers, or registering licenses).",
    "status": "Read-only queries to pull the live, active state of your conferencing systems, live calls, and connected participants.",
    "command": "Outbound calling, moderator controls, and platform operations (e.g. dial-out, muting participants, locking/unlocking, LDAP synchronization, or taking platform snapshots).",
    "history": "Access to past conference logs and history records (CDRs) for auditing and reporting.",
}

# Create tag folders
folders = {}


def get_or_create_folder(tag_name):
    if tag_name not in folders:
        desc = folder_descriptions.get(
            tag_name.lower(), f"Endpoints related to {tag_name}."
        )
        folder_obj = {"name": tag_name, "description": desc, "item": []}
        folders[tag_name] = folder_obj
        collection["item"].append(folder_obj)
    return folders[tag_name]


# Custom test scripts for request chaining
test_scripts = {
    "/api/admin/status/v1/conference/": [
        "// Request Chaining: Automatically save active conference details",
        "if (pm.response.code === 200) {",
        "    const data = pm.response.json();",
        "    if (data.objects && data.objects.length > 0) {",
        "        pm.collectionVariables.set('active_conference_id', data.objects[0].id);",
        "        pm.collectionVariables.set('active_conference_name', data.objects[0].name);",
        "        console.log('Chaining: Saved active_conference_id -> ' + data.objects[0].id);",
        "        console.log('Chaining: Saved active_conference_name -> ' + data.objects[0].name);",
        "    }",
        "}",
    ],
    "/api/admin/status/v1/participant/": [
        "// Request Chaining: Automatically save active participant ID",
        "if (pm.response.code === 200) {",
        "    const data = pm.response.json();",
        "    if (data.objects && data.objects.length > 0) {",
        "        pm.collectionVariables.set('active_participant_id', data.objects[0].id);",
        "        console.log('Chaining: Saved active_participant_id -> ' + data.objects[0].id);",
        "    }",
        "}",
    ],
}

# Pre-populated request bodies for commands
command_bodies = {
    "/api/admin/command/v1/participant/dial/": {
        "conference_alias": "meet.alice@pexip.local",
        "destination": "alice@example.com",
        "routing": "routing_rule",
        "protocol": "sip",
        "role": "guest",
        "system_location": "London",
        "remote_display_name": "Alice Parkes",
    },
    "/api/admin/command/v1/participant/disconnect/": {
        "participant_id": "{{active_participant_id}}"
    },
    "/api/admin/command/v1/participant/mute/": {
        "participant_id": "{{active_participant_id}}"
    },
    "/api/admin/command/v1/participant/unmute/": {
        "participant_id": "{{active_participant_id}}"
    },
    "/api/admin/command/v1/participant/unlock/": {
        "participant_id": "{{active_participant_id}}"
    },
    "/api/admin/command/v1/participant/transfer/": {
        "participant_id": "{{active_participant_id}}",
        "conference_alias": "meet.bob@pexip.local",
        "role": "guest",
    },
    "/api/admin/command/v1/participant/role/": {
        "participant_id": "{{active_participant_id}}",
        "role": "chair",
    },
    "/api/admin/command/v1/conference/disconnect/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/lock/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/unlock/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/mute_guests/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/unmute_guests/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/transform_layout/": {
        "conference_id": "{{active_conference_id}}",
        "enable_overlay_text": True,
        "layout": "4:0",
    },
    "/api/admin/command/v1/platform/backup_create/": {
        "passphrase": "backup_secret_passphrase",
        "request": False,
    },
    "/api/admin/command/v1/platform/backup_restore/": {
        "passphrase": "backup_secret_passphrase",
        "package": "base64_encoded_backup_data_or_file_content",
    },
    "/api/admin/command/v1/conference/sync/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/send_conference_email/": {
        "conference_id": "{{active_conference_id}}"
    },
    "/api/admin/command/v1/conference/send_device_email/": {
        "device_id": "12345678-abcd-1234-abcd-1234567890ab"
    },
    "/api/admin/command/v1/platform/certificates_import/": {
        "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----",
        "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
    },
    "/api/admin/command/v1/platform/start_cloudnode/": {
        "instance_id": "i-0123456789abcdef0"
    },
    "/api/admin/command/v1/platform/snapshot/": {"limit": 12, "request": False},
    "/api/admin/command/v1/platform/upgrade/": {"version": "v40.0"},
    "/api/admin/command/v1/platform/software_bundle/": {
        "package": "base64_encoded_software_bundle_data"
    },
}


def generate_mock_data(schema_or_ref, spec, exclude_readonly=False, visited=None):
    if visited is None:
        visited = set()

    if isinstance(schema_or_ref, dict) and "$ref" in schema_or_ref:
        ref_path = schema_or_ref["$ref"]
        schema_name = ref_path.split("/")[-1]
        if schema_name in visited:
            return None
        visited.add(schema_name)
        schema_def = spec.get("components", {}).get("schemas", {}).get(schema_name)
        if not schema_def:
            return None
        return generate_mock_data(schema_def, spec, exclude_readonly, visited)

    if not isinstance(schema_or_ref, dict):
        return None

    s_type = schema_or_ref.get("type", "string")

    if s_type == "object":
        properties = schema_or_ref.get("properties", {})
        obj_data = {}
        for prop_name, prop_val in properties.items():
            if exclude_readonly and prop_val.get("readOnly", False):
                continue

            # Special case for "meta" object in list responses
            if prop_name == "meta" and not exclude_readonly:
                obj_data[prop_name] = {
                    "limit": 20,
                    "offset": 0,
                    "total_count": 1,
                    "next": None,
                    "previous": None,
                }
                continue

            obj_data[prop_name] = generate_mock_field(
                prop_name, prop_val, spec, exclude_readonly, visited.copy()
            )
        return obj_data

    elif s_type == "array":
        items_schema = schema_or_ref.get("items", {})
        item_val = generate_mock_data(items_schema, spec, exclude_readonly, visited)
        return [item_val] if item_val is not None else []

    else:
        return generate_mock_field(
            "value", schema_or_ref, spec, exclude_readonly, visited
        )


def generate_mock_field(prop_name, field_schema, spec, exclude_readonly, visited):
    if isinstance(field_schema, dict) and "$ref" in field_schema:
        return generate_mock_data(field_schema, spec, exclude_readonly, visited)

    if not isinstance(field_schema, dict):
        return ""

    s_type = field_schema.get("type", "string")
    if s_type in ["object", "array"]:
        return generate_mock_data(field_schema, spec, exclude_readonly, visited)

    if "enum" in field_schema and field_schema["enum"]:
        return field_schema["enum"][0]

    if (
        "default" in field_schema
        and field_schema["default"] is not None
        and field_schema["default"] != "No default"
    ):
        return field_schema["default"]

    name_lower = prop_name.lower()
    if s_type == "string":
        if "uuid" in name_lower or prop_name == "id":
            return "12345678-abcd-1234-abcd-1234567890ab"
        elif "time" in name_lower or "date" in name_lower:
            return "2026-06-01T08:45:00.000000Z"
        elif "email" in name_lower:
            return "admin@example.com"
        elif "uri" in name_lower or "url" in name_lower:
            return f"/api/admin/configuration/v1/{prop_name}/1/"
        elif "ip" in name_lower or "host" in name_lower or "server" in name_lower:
            return "192.168.1.1"
        elif "password" in name_lower or "secret" in name_lower:
            return "********"
        elif "alias" in name_lower:
            return f"sample_{prop_name}"
        else:
            return f"sample_{prop_name}"
    elif s_type == "integer":
        if "limit" in name_lower:
            return 20
        elif "offset" in name_lower:
            return 0
        elif "port" in name_lower:
            return 443
        else:
            return 1
    elif s_type == "number":
        return 1.0
    elif s_type == "boolean":
        return True

    return ""


paths = spec.get("paths", {})
for path, path_info in paths.items():
    # Convert path variables from OpenAPI {param} to Postman :param
    postman_path = path.replace("{id}", ":id")

    # Check if path variable :id exists and bind it to our dynamic variables if applicable
    url_variables = []
    if "{id}" in path:
        default_val = ""
        if "conference" in path:
            default_val = "{{active_conference_id}}"
        elif "participant" in path:
            default_val = "{{active_participant_id}}"

        url_variables.append(
            {
                "key": "id",
                "value": default_val,
                "description": "The unique resource identifier.",
            }
        )

    for method, method_info in path_info.items():
        summary = method_info.get("summary", f"{method.upper()} {path}")
        tags = method_info.get("tags", ["general"])
        folder = get_or_create_folder(tags[0])

        # Parse query params
        query_list = []
        parameters = method_info.get("parameters", [])
        for param in parameters:
            if param.get("in") == "query":
                p_name = param.get("name")
                p_schema = param.get("schema", {})
                p_default = p_schema.get("default", "")

                # Set default values for limit and offset, leave others blank
                val = str(p_default)
                if p_name not in ["limit", "offset"]:
                    val = ""

                # CRITICAL: Disable optional query filters by default to prevent Tastypie crashes!
                is_disabled = p_name not in ["limit", "offset"]

                query_list.append(
                    {
                        "key": p_name,
                        "value": val,
                        "description": param.get("description", ""),
                        "disabled": is_disabled,
                    }
                )

        # Build URL structure
        path_parts = [p for p in postman_path.strip("/").split("/") if p]
        if postman_path.endswith("/"):
            path_parts.append("")
        url_obj = {
            "raw": f"{{{{baseUrl}}}}{postman_path}",
            "host": ["{{baseUrl}}"],
            "path": path_parts,
        }
        if url_variables:
            url_obj["variable"] = url_variables
        if query_list:
            url_obj["query"] = query_list
            raw_queries = "&".join(
                [
                    f"{q['key']}={q['value']}"
                    for q in query_list
                    if not q.get("disabled")
                ]
            )
            if raw_queries:
                url_obj["raw"] += f"?{raw_queries}"

        # Construct Postman Item
        postman_item = {
            "name": summary,
            "request": {
                "method": method.upper(),
                "header": [{"key": "Content-Type", "value": "application/json"}],
                "description": method_info.get("description", ""),
                "url": url_obj,
            },
        }

        # Inject Request Bodies
        body_data = None
        if method.lower() in ["post", "patch"]:
            # Check if this is a command with a pre-configured mock body
            body_data = command_bodies.get(path)
            if not body_data:
                req_schema = (
                    method_info.get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                if req_schema:
                    body_data = generate_mock_data(
                        req_schema, spec, exclude_readonly=True
                    )

            if body_data is None:
                body_data = {}

            postman_item["request"]["body"] = {
                "mode": "raw",
                "raw": json.dumps(body_data, indent=4),
            }

        # Build Postman Response Examples
        postman_item["response"] = []
        responses = method_info.get("responses", {})
        for status_code_str, resp_info in responses.items():
            try:
                status_code = int(status_code_str)
            except ValueError:
                continue

            # We generate examples for typical status codes
            if status_code not in [200, 201, 202, 204, 400, 404]:
                continue

            status_text = "OK"
            if status_code == 201:
                status_text = "Created"
            elif status_code == 202:
                status_text = "Accepted"
            elif status_code == 204:
                status_text = "No Content"
            elif status_code == 400:
                status_text = "Bad Request"
            elif status_code == 404:
                status_text = "Not Found"

            # Generate Mock Response Body
            resp_body_str = ""
            resp_schema = (
                resp_info.get("content", {}).get("application/json", {}).get("schema")
            )
            if resp_schema:
                resp_mock_data = generate_mock_data(
                    resp_schema, spec, exclude_readonly=False
                )
                if resp_mock_data is not None:
                    resp_body_str = json.dumps(resp_mock_data, indent=4)
            elif status_code in [400, 404]:
                resp_body_str = json.dumps(
                    {"error": resp_info.get("description", "An error occurred.")},
                    indent=4,
                )

            # Generate Response Headers
            example_headers = [{"key": "Content-Type", "value": "application/json"}]
            if status_code == 201:
                example_headers.append(
                    {
                        "key": "Location",
                        "value": f"https://your-pexip-manager.example.com{postman_path}1/",
                    }
                )

            # Original request for this example
            orig_req = {
                "method": method.upper(),
                "header": [{"key": "Content-Type", "value": "application/json"}],
                "url": url_obj,
            }
            if body_data is not None:
                orig_req["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(body_data, indent=4),
                }

            postman_item["response"].append(
                {
                    "name": f"{status_code} {status_text}",
                    "originalRequest": orig_req,
                    "status": status_text,
                    "code": status_code,
                    "_postman_previewlanguage": "json",
                    "header": example_headers,
                    "cookie": [],
                    "body": resp_body_str,
                }
            )

        # Build Test Assertions & Chaining Scripts
        test_exec_lines = []
        success_codes = []
        responses = method_info.get("responses", {})
        for status_code_str in responses.keys():
            if status_code_str.startswith("2"):
                try:
                    success_codes.append(int(status_code_str))
                except ValueError:
                    continue
        if not success_codes:
            success_codes = [200]

        test_exec_lines.append("// Test Assertion: Verify successful HTTP response")
        if len(success_codes) == 1:
            expected_code = success_codes[0]
            status_text = "OK"
            if expected_code == 201:
                status_text = "Created"
            elif expected_code == 204:
                status_text = "No Content"
            elif expected_code == 202:
                status_text = "Accepted"
            test_exec_lines.append(
                f'pm.test("Status code is {expected_code} {status_text}", function () {{'
            )
            test_exec_lines.append(f"    pm.response.to.have.status({expected_code});")
            test_exec_lines.append("});")
        else:
            codes_list_str = ", ".join(map(str, success_codes))
            test_exec_lines.append(
                f'pm.test("Status code is one of: {codes_list_str}", function () {{'
            )
            test_exec_lines.append(
                f"    pm.expect(pm.response.code).to.be.oneOf([{codes_list_str}]);"
            )
            test_exec_lines.append("});")

        # Append dynamic variable chaining script if it exists
        chaining_script = test_scripts.get(path)
        if chaining_script:
            test_exec_lines.append("")
            test_exec_lines.extend(chaining_script)

        # Inject into Postman event list
        postman_item["event"] = [
            {
                "listen": "test",
                "script": {"exec": test_exec_lines, "type": "text/javascript"},
            }
        ]

        # Add to tag folder list
        folder["item"].append(postman_item)

# Sort items for folder cleanliness
collection["item"] = sorted(collection["item"], key=lambda x: x["name"])

# Write out collection file
with open(output_path, "w") as f:
    json.dump(collection, f, indent=2)

print(f"[SUCCESS] Postman collection generated at '{output_path}'")

# Generate and write companion environment file
env_output_path = "pexip_postman_environment.json"
environment = {
    "id": "8c5b36bd-23c2-48df-9f93-8472a15f013d",
    "name": "Pexip Infinity REST API Environment",
    "values": [
        {
            "key": "baseUrl",
            "value": "https://your-pexip-manager.example.com",
            "type": "default",
            "enabled": True,
        },
        {
            "key": "pexip_admin_username",
            "value": "admin",
            "type": "default",
            "enabled": True,
        },
        {"key": "pexip_admin_password", "value": "", "type": "secret", "enabled": True},
        {"key": "client_id", "value": "", "type": "default", "enabled": True},
        {"key": "client_private_key", "value": "", "type": "secret", "enabled": True},
        {
            "key": "pmlib_code",
            "value": pmlib_bundle_code,
            "type": "secret",
            "enabled": True,
        },
    ],
    "_postman_variable_scope": "environment",
}

with open(env_output_path, "w") as f:
    json.dump(environment, f, indent=2)

print(
    f"[SUCCESS] Companion Postman Environment template generated at '{env_output_path}'"
)
print(
    "Drag and drop both the collection and environment files into Postman for instant setup with masked credentials."
)
