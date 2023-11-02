import oci,json,argparse,os,sys

# utilities
def saveFile(data, file_path):
    with open(file_path, "w") as file:
        # Write the variable to the file
        file.write(data)

# Argument Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--profile',dest='profile_name',action='store',
                    default="DEFAULT", help='the oci profile name')

parser.add_argument('--profile-location',dest='profile_location',action='store',
                    default="~/.oci/config", help='the oci config location')

parser.add_argument(dest='compartment_id', type=str, nargs=1,
                    help='the compartment id')

parser.add_argument('--debug', action='store_true', help='will print out debug messages')
parser.add_argument('--debugFiles', action='store_true', help='will output some files in a "debug" subdirectory')


args = parser.parse_args()

# Summary of what you get from args
profile_name = args.profile_name
compartmentId = args.compartment_id[0]
debug = args.debug
debugFiles = args.debugFiles


# Config
config = oci.config.from_file(profile_name=args.profile_name,file_location=args.profile_location)
subscribed_regions = oci.identity.IdentityClient(config).list_region_subscriptions(tenancy_id=config["tenancy"]).data

# Init the search clients
search_clients = {}
for region in subscribed_regions:
    config["region"] = region.region_name
    search_clients[region.region_name] = oci.resource_search.ResourceSearchClient(config)

# Search
# query_string = "query all resources return allAdditionalFields where compartmentId='{}' ".format(args.compartment_id[0])
 

def queryOCI(compartmentId):
    query_string = "query all resources where compartmentId='{}' sorted by displayName asc".format(compartmentId)

    data = []

    for region_name, search_client in search_clients.items():
        search_resources_response = search_client.search_resources(search_details=oci.resource_search.models.StructuredSearchDetails(
            type="Structured",
            query=query_string,
            matching_context_type="NONE"), limit=1000)
        newdata = search_resources_response.data.items 
        
        while search_resources_response.has_next_page :
            search_resources_response = search_client.search_resources(search_details=oci.resource_search.models.StructuredSearchDetails(
            type="Structured",
            query=query_string,
            matching_context_type="NONE"), limit=1000, page=search_resources_response.next_page)
            newdata += search_resources_response.data.items
        
        data += newdata

        if (debug) :
            print("DEBUG: {} elements acquired from OCI for compartment {} in region {}.".format(len(newdata), compartmentId, region_name))

    if (debug):
        print("DEBUG: {} elements acquired from OCI for compartment {} (total in all regions).".format(len(data),compartmentId))
        
    return data

debugFileNumber = 0
def makeJsonFromOCI(data): 
    global debugFileNumber
    newjson = {}

    for item in data :

        try:
            if item.lifecycle_state in ['DELETING','DELETED','TERMINATING','TERMINATED']:
                continue
                #pass
        except:
            pass

        try:
            newjson[item.resource_type]
        except:
            newjson[item.resource_type] = {}
            newjson[item.resource_type]["number"] = 0
            newjson[item.resource_type]["items"] = {}

        try:
            if newjson[item.resource_type]["items"][item.display_name] == item.identifier:
                continue
        except:
            newjson[item.resource_type]["number"] = newjson[item.resource_type]["number"] + 1
            newjson[item.resource_type]["items"][item.display_name] = item.identifier


    if (debugFiles):
        os.makedirs("debug", exist_ok=True)
        saveFile(json.dumps(newjson),"debug/output-{}.json".format(debugFileNumber))
        debugFileNumber+=1

    return json.dumps(newjson)


def makeTree(compartmentId,topLevelNodeName):
    data = '{{"id": "{}", "parent": "#", "text": "<b>{}</b>", "state" :{{"opened":"true"}}}},\n'.format(topLevelNodeName,compartmentId)
    query = queryOCI(compartmentId)

    data += makeSubTree(json.loads(makeJsonFromOCI(query)), topLevelNodeName)

    # we need to remove the last comma
    return data[:-2]

def makeSubTree(data,parent_node_name):
    print('.', end='')
    sys.stdout.flush()
    newjson = ""
  
    for position, (key, value) in enumerate(data.items()):
        node_id = "{}_{}".format(parent_node_name, position)
        text = "<b>{}</b> ({})".format(key, value.get("number"))

        if key == 'Compartment':
            newjson += '{{"id": "{}", "parent": "{}", "text": "{}","state" :{{"opened":"true"}}}},\n'.format(node_id,parent_node_name,text)
        else :
            newjson += '{{"id": "{}", "parent": "{}", "text": "{}"}},\n'.format(node_id,parent_node_name,text)
        

        for position2, (key2, value2) in enumerate(value.get("items").items()):
            node_item_id = "{}_{}".format(node_id, position2)

            if key == 'Compartment':
                text = "<b>{}</b> ({})".format(key2,value2)
                newjson +=  '{{"id": "{}", "parent": "{}", "text": "{}"}},\n'.format(node_item_id,node_id,text)
                # Recursion
                newjson += makeSubTree(json.loads(makeJsonFromOCI(queryOCI(value2))),node_item_id)
            else :
                text = "<b>{}</b> ({})".format(key2,value2)
                newjson +=  '{{"id": "{}", "parent": "{}", "text": "{}", "icon":"images/leaf.png"}},\n'.format(node_item_id,node_id,text)
 
    return newjson



print("Generating the json file (can be long !) ..", end='')
sys.stdout.flush()
json = makeTree(compartmentId,"top")
print()

# the [] are there for use by javascript
print("Writing the data.json file...")
saveFile("[" + json + "]", "/home/evinck/Documents/OCI-Commander/DocumentRoot/data.json")


