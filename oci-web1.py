import argparse
import json
import os
import re
import sys
from datetime import datetime

import oci


DISPLAY_NAME_ESCAPE_PATTERN = r"\\[a-zA-Z]"
DEFAULT_OUTPUT_LOCATION = "DocumentRoot/data.json"


# Write a string payload to a file on disk.
def save_to_file(data, file_path):
    with open(file_path, "w") as file:
        file.write(data)


# Build the command-line parser used by the generator script.
def build_arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        dest="profile_name",
        action="store",
        required=False,
        default="DEFAULT",
        help="the oci profile name",
    )
    parser.add_argument(
        "--profile-location",
        dest="profile_location",
        action="store",
        default="~/.oci/config",
        help="the oci config location",
    )
    parser.add_argument(
        "--compartment_id",
        dest="compartment_id",
        action="store",
        required=False,
        help="the compartment id",
    )
    parser.add_argument(
        "--output",
        dest="output_location",
        action="store",
        default=DEFAULT_OUTPUT_LOCATION,
        help="the data.json location",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="will print out debug messages",
    )
    parser.add_argument(
        "--debugFiles",
        action="store_true",
        help='will output some files in a "debug" subdirectory',
    )
    return parser


# Query OCI, build the tree payload, and optionally write data.json.
def generate_output(
    profile_name="DEFAULT",
    profile_location="~/.oci/config",
    compartment_id=None,
    output_location=DEFAULT_OUTPUT_LOCATION,
    debug=False,
    debug_files=False,
):
    config = oci.config.from_file(
        profile_name=profile_name,
        file_location=profile_location,
    )
    subscribed_regions = oci.identity.IdentityClient(config).list_region_subscriptions(
        tenancy_id=config["tenancy"]
    ).data

    run_timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z%z")

    identity_client = oci.identity.IdentityClient(config)
    tenancy = identity_client.get_tenancy(config["tenancy"]).data
    tenancy_name = tenancy.name

    if compartment_id is None:
        print("No compartment specified, will go for the whole tenancy (can be long !).")
        compartment_id = config["tenancy"]

    search_clients = {}
    for region in subscribed_regions:
        config["region"] = region.region_name
        search_clients[region.region_name] = oci.resource_search.ResourceSearchClient(
            config
        )

    debug_file_number = 0

    # Query OCI Search across all subscribed regions for one compartment.
    def query_oci(target_compartment_id):
        nonlocal debug_file_number
        query_string = (
            "query all resources where compartmentId='{}' sorted by displayName asc"
        ).format(target_compartment_id)

        data = []

        for region_name, search_client in search_clients.items():
            search_resources_response = search_client.search_resources(
                search_details=oci.resource_search.models.StructuredSearchDetails(
                    type="Structured",
                    query=query_string,
                    matching_context_type="NONE",
                ),
                limit=1000,
            )
            newdata = search_resources_response.data.items

            while search_resources_response.has_next_page:
                search_resources_response = search_client.search_resources(
                    search_details=oci.resource_search.models.StructuredSearchDetails(
                        type="Structured",
                        query=query_string,
                        matching_context_type="NONE",
                    ),
                    limit=1000,
                    page=search_resources_response.next_page,
                )
                newdata += search_resources_response.data.items

            data += newdata

            if debug:
                print(
                    "DEBUG: {} elements acquired from OCI for compartment {} in region {}.".format(
                        len(newdata), target_compartment_id, region_name
                    )
                )

        if debug:
            print(
                "DEBUG: {} elements acquired from OCI for compartment {} (total in all regions).".format(
                    len(data), target_compartment_id
                )
            )

        if debug_files:
            os.makedirs("debug", exist_ok=True)
            save_to_file(str(data), "debug/output-{}.json".format(debug_file_number))
            debug_file_number += 1

        return data

    # Recursively collect OCI resources into the in-memory database.
    def fill_database(database, target_compartment_id):
        if not debug:
            print(".", end="")
            sys.stdout.flush()

        data = query_oci(target_compartment_id)
        for item in data:
            try:
                database[item.identifier]
                continue
            except KeyError:
                pass

            lifecycle_state = getattr(item, "lifecycle_state", None)
            if isinstance(lifecycle_state, str) and lifecycle_state.upper() in [
                "DELETING",
                "DELETED",
                "TERMINATING",
                "TERMINATED",
            ]:
                continue

            if item.resource_type == "Compartment":
                try:
                    database[item.identifier]
                    continue
                except KeyError:
                    fill_database(database, item.identifier)

            key = item.identifier
            value_dict = {}
            value_dict["parent"] = target_compartment_id
            value_dict["type"] = item.resource_type
            value_dict["display_name"] = re.sub(
                DISPLAY_NAME_ESCAPE_PATTERN, "", str(item.display_name)
            )
            value_dict["rawdata"] = item.__dict__

            database[key] = value_dict

    # Extract the OCI region name from an OCID when possible.
    def guess_region_from_ocid(ocid):
        match = re.search(r"\.oc1\.([^\.]*)\.", ocid)
        if match:
            return match.group(1)
        return subscribed_regions[0].region_name

    # Build the frontend metadata attached to one tree node.
    def make_js_tree_data_item(database, ocid):
        data_item = {}
        data_item["node_type"] = "item"
        data_item["display_name"] = database[ocid]["display_name"]
        data_item["ocid"] = ocid
        data_item["url"] = (
            "https://cloud.oracle.com/?tenant="
            + tenancy_name
            + "&search?q="
            + ocid
            + "&region="
            + guess_region_from_ocid(ocid)
        )
        return data_item

    default_icon = "images/leaf.png"
    icon_chooser = {
        "Directory": "images/Directory.svg",
        "Compartment": "images/Compartments.svg",
        "AutonomousDatabase": "images/Autonomous Database.svg",
        "Bucket": "images/Buckets.svg",
        "Instance": "images/Virtual Machine.svg",
        "User": "images/User.svg",
        "Group": "images/User Group unisex.svg",
    }

    # Build the resource subtree grouped by resource type.
    def make_js_subtree_sorted_by_type(database, ocid):
        njson = ""
        subnode_keys = [key for key, value in database.items() if value["parent"] == ocid]

        types_count = {}
        for key in subnode_keys:
            try:
                types_count[database[key]["type"]] += 1
            except KeyError:
                types_count[database[key]["type"]] = 1

        for key, value in types_count.items():
            data_item = {"node_type": key}
            data_item = json.dumps(data_item)
            if key == "Compartment":
                opened_state = "true"
            else:
                opened_state = "false"

            njson += (
                '{{"id": "{}_{}", "parent": "{}", "text": "<b>{} ({})</b>", "data":{}, '
                '"state" :{{"opened":{}}}}},\n'
            ).format(ocid, key, ocid, key, value, data_item, opened_state)

        for key in subnode_keys:
            data_item = json.dumps(make_js_tree_data_item(database, key))
            icon = icon_chooser.get(database[key]["type"], default_icon)

            njson += (
                '{{"id": "{}", "parent": "{}_{}", "text": "<b>{}</b>", "icon":"{}", '
                '"data" : {}}},\n'
            ).format(
                key,
                ocid,
                database[key]["type"],
                database[key]["display_name"],
                icon,
                data_item,
            )

            if database[key]["type"] == "Compartment":
                njson += make_js_subtree_sorted_by_type(database, key)

        return njson

    # Build the complete jsTree payload starting at the selected compartment.
    def make_js_tree(database, top_ocid):
        tree_json = (
            '{{"id": "{}", "parent": "#", "text": "<b>{}</b>", '
            '"state" :{{"opened":true}}}},\n'
        ).format(top_ocid, top_ocid)
        tree_json += make_js_subtree_sorted_by_type(database, top_ocid)
        return tree_json[:-2]

    print("Querying OCI and making up internal database (can be long !) ..", end="")
    sys.stdout.flush()

    database = {}
    fill_database(database, compartment_id)
    print(".")

    if debug_files:
        save_to_file(str(database), "database.debug")

    tree_json = make_js_tree(database, compartment_id)

    output_payload = {
        "generated_at": run_timestamp,
        "nodes": json.loads("[" + tree_json + "]"),
    }

    if output_location:
        print("Writing the data.json file to {}".format(output_location))
        save_to_file(json.dumps(output_payload), output_location)

    return output_payload


# Parse command-line arguments and run the OCI export once.
def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    generate_output(
        profile_name=args.profile_name,
        profile_location=args.profile_location,
        compartment_id=args.compartment_id,
        output_location=args.output_location,
        debug=args.debug,
        debug_files=args.debugFiles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
