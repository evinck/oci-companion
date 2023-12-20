import oci, json, argparse, os, sys, re

# utilities
def save2File(data, file_path):
    with open(file_path, "w") as file:
        # Write the variable to the file
        file.write(data)


# Argument Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--profile', dest='profile_name', action='store', required=False,
                    default="DEFAULT", help='the oci profile name')
parser.add_argument('--profile-location', dest='profile_location', action='store',
                    default="~/.oci/config", help='the oci config location')
parser.add_argument('--compartment_id', dest='compartment_id', action='store', required=False,
                    help='the compartment id')
parser.add_argument('--output', dest='output_location', action='store',
                    default="DocumentRoot/data.json", help='the data.json location')
parser.add_argument('--debug', action='store_true',
                    help='will print out debug messages')
parser.add_argument('--debugFiles', action='store_true',
                    help='will output some files in a "debug" subdirectory')
args = parser.parse_args()

# Config
config = oci.config.from_file(
    profile_name=args.profile_name, file_location=args.profile_location)
subscribed_regions = oci.identity.IdentityClient(
    config).list_region_subscriptions(tenancy_id=config["tenancy"]).data

# Summary of what you get from args
profile_name = args.profile_name
output_location = args.output_location
debug = args.debug
debugFiles = args.debugFiles

# Set the compartment to start from
compartmentId = args.compartment_id
if (compartmentId == None):
    print("No compartment specified, will go for the whole tenancy (can be long !).")
    compartmentId = config["tenancy"]

# Init the search clients
search_clients = {}
for region in subscribed_regions:
    config["region"] = region.region_name
    search_clients[region.region_name] = oci.resource_search.ResourceSearchClient(
        config)

# Search
# query_string = "query all resources return allAdditionalFields where compartmentId='{}' ".format(args.compartment_id[0])
def queryOCI(compartmentId):
    query_string = "query all resources where compartmentId='{}' sorted by displayName asc".format(
        compartmentId)

    data = []

    for region_name, search_client in search_clients.items():
        search_resources_response = search_client.search_resources(search_details=oci.resource_search.models.StructuredSearchDetails(
            type="Structured",
            query=query_string,
            matching_context_type="NONE"), limit=1000)
        newdata = search_resources_response.data.items

        while search_resources_response.has_next_page:
            search_resources_response = search_client.search_resources(search_details=oci.resource_search.models.StructuredSearchDetails(
                type="Structured",
                query=query_string,
                matching_context_type="NONE"), limit=1000, page=search_resources_response.next_page)
            newdata += search_resources_response.data.items

        data += newdata

        if (debug):
            print("DEBUG: {} elements acquired from OCI for compartment {} in region {}.".format(
                len(newdata), compartmentId, region_name))

    if (debug):
        print("DEBUG: {} elements acquired from OCI for compartment {} (total in all regions).".format(
            len(data), compartmentId))

    return data


pattern=r'\\[a-zA-Z]'
debugFileNumber = 0
def makeJsonFromOCI(data):
    global debugFileNumber
    global pattern
    newjson = {}

    for item in data:

        try:
            if str.upper(item.lifecycle_state) in ['DELETING', 'DELETED', 'TERMINATING', 'TERMINATED']:
                continue
                # pass
        except:
            pass

        try:
            newjson[item.resource_type]
        except:
            newjson[item.resource_type] = {}
            newjson[item.resource_type]["number"] = 0
            newjson[item.resource_type]["items"] = {}

        # This below to get rid of \a \c etc... in display names
        display_name = re.sub(pattern,'',str(item.display_name))
        try:
            # this will handle duplicates (from regions) : for ressources like user,group, etc..
            if newjson[item.resource_type]["items"][display_name] == item.identifier:
                continue
        except:
            newjson[item.resource_type]["number"] = newjson[item.resource_type]["number"] + 1
            newjson[item.resource_type]["items"][display_name] = item.identifier

    # TODO sort the json based on 1/ resource_type and 2/ items
    # sort a dict ?

    if (debugFiles):
        os.makedirs("debug", exist_ok=True)
        save2File(json.dumps(newjson),
                 "debug/output-{}.json".format(debugFileNumber))
        debugFileNumber += 1

    return json.dumps(newjson)


def makeTree(compartmentId, topLevelNodeName):
    data = '{{"id": "{}", "parent": "#", "text": "<b>{}</b>", "state" :{{"opened":"true"}}}},\n'.format(
        topLevelNodeName, compartmentId)
    query = queryOCI(compartmentId)

    data += makeSubTree(json.loads(makeJsonFromOCI(query)), topLevelNodeName)

    # we need to remove the last comma
    return data[:-2]


def makeSubTree(data, parent_node_name):
    # for the progress bar
    if (not debug) :
        print('.', end='')
        sys.stdout.flush()

    newjson = ""

    for position, (key, value) in enumerate(data.items()):
        node_id = "{}_{}".format(parent_node_name, position)
        text = "<b>{}</b> ({})".format(key, value.get("number"))

        if key == 'Compartment':
            newjson += '{{"id": "{}", "parent": "{}", "text": "{}","state" :{{"opened":"true"}}}},\n'.format(
                node_id, parent_node_name, text)
        else:
            newjson += '{{"id": "{}", "parent": "{}", "text": "{}"}},\n'.format(
                node_id, parent_node_name, text)

        for position2, (key2, value2) in enumerate(value.get("items").items()):
            node_item_id = "{}_{}".format(node_id, position2)

            if key == 'Compartment':
                text = "<b>{}</b> ({})".format(key2, value2)
                newjson += '{{"id": "{}", "parent": "{}", "text": "{}"}},\n'.format(
                    node_item_id, node_id, text)
                # Recursion
                newjson += makeSubTree(json.loads(
                    makeJsonFromOCI(queryOCI(value2))), node_item_id)
            else:
                text = "<b>{}</b> ({})".format(key2, value2)
                newjson += '{{"id": "{}", "parent": "{}", "text": "{}", "icon":"images/leaf.png"}},\n'.format(
                    node_item_id, node_id, text)

    return newjson


print("Generating the json file (can be long !) ..", end='')
sys.stdout.flush()
json = makeTree(compartmentId, "top")
print()

# the [] are there for use by javascript
print("Writing the data.json file to {}".format(output_location))
save2File("[" + json + "]", output_location)
