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

# Summary of what you get from args
profile_name = args.profile_name
output_location = args.output_location
debug = args.debug
debugFiles = args.debugFiles
compartmentId = args.compartment_id

# OCI Config
config = oci.config.from_file(
    profile_name=args.profile_name, file_location=args.profile_location)
subscribed_regions = oci.identity.IdentityClient(
    config).list_region_subscriptions(tenancy_id=config["tenancy"]).data

# Set the compartment to start from
if (compartmentId == None):
    print("No compartment specified, will go for the whole tenancy (can be long !).")
    compartmentId = config["tenancy"]

# Init the search clients
search_clients = {}
for region in subscribed_regions:
    config["region"] = region.region_name
    search_clients[region.region_name] = oci.resource_search.ResourceSearchClient(
        config)

# Fill in the database with OCI
# TODO : avoid searching identity resources each time
debugFileNumber=0
def queryOCI(compartmentId):
    global debugFileNumber
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

    if (debugFiles):
        os.makedirs("debug", exist_ok=True)
        save2File(str(data),
                 "debug/output-{}.json".format(debugFileNumber))
        debugFileNumber += 1

    return data

# Database
# each Database entry should be like {"ocid...",{"parent":"xxx","type":"xxx","display":"name","rawdata":"xxxx"}}
pattern=r'\\[a-zA-Z]'
def fillDatabase(database, compartmentId):

    # for the progress bar
    if (not debug) :
        print('.', end='')
        sys.stdout.flush()

    data = queryOCI(compartmentId)
    for item in data:
        # skip if item has already been processed
        try :
            database[item.identifier]
            continue
        except:
            pass
        # skip if state is not useful for us
        # try/except because some resources don't have the lifecycle_state value
        try :
            if str.upper(item.lifecycle_state) in ['DELETING', 'DELETED', 'TERMINATING', 'TERMINATED']:
                continue
        except:
            pass

        # Recursion for compartments
        if item.resource_type == 'Compartment':
            # Check if compartment hasn't been processed already (identity information got multiple times - from each region)
            try :
                database[item.identifier]
                continue
            except:
                fillDatabase(database, item.identifier)

        key = item.identifier
        value_dict = {}
        value_dict['parent'] = compartmentId
        value_dict['type'] = item.resource_type
        # clean up the display name
        display_name = re.sub(pattern,'',str(item.display_name))
        value_dict["display_name"]= display_name
        value_dict['rawdata'] = item.__dict__

        database[key]=value_dict

    return 

# The main to call
def makeJSTree(database, top_ocid):
    json = '{{"id": "{}", "parent": "#", "text": "<b>{}</b>", "state" :{{"opened":true}}}},\n'.format(top_ocid, top_ocid)
    
    #json += makeJSSubTree(database, top_ocid)
    json += makeJSSubTreeSortedByType(database, top_ocid)
    #json += makeJSSubTreeConsolidatedByType(database, top_ocid)

    # remove the last comma
    return json[:-2]

# Regular SubTree
def makeJSSubTree(database, ocid):
    json = ""

    subnode_keys = [key for key,value in database.items() if value['parent'] == ocid ]

    for key in subnode_keys:
        # json +=  '{{"id": "{}", "parent": "{}", "text": "<b>{}</b>", "state" :{{"opened":"true"}}}},\n'.format(key, ocid, database[key]["display_name"])
        json +=  '{{"id": "{}", "parent": "{}", "text": "<b>{}</b>"}},\n'.format(key, ocid, database[key]["display_name"])
        # recursion
        if database[key]['type'] == 'Compartment':
            json += makeJSSubTree(database, key)
    return json

# TODO: doesn't work for buckets 
def guess_region_fromocid(ocid):
    region = ""
    pattern = r'\.oc1\.([^\.]*)\.'
    match = re.search(pattern, ocid)
    region = match.group(1) if match else subscribed_regions[0]

    return region

# We'll use this one to build the data field 
def makeJSTreeDataItem(database, ocid):
    # TypeError: Object of type datetime is not JSON serializable
    #dataItem = database[ocid]['rawdata']
    dataItem={}
    dataItem['node_type']="item"
    dataItem['display_name']=database[ocid]['display_name']
    dataItem['ocid']=ocid
    dataItem['url']="https://cloud.oracle.com/search?q=" + ocid + "&region=" + guess_region_fromocid(ocid)
     
    return dataItem

# IconChooser
DefaultIcon = "images/leaf.png"
IconChooser = {
    "Directory" :"images/Directory.svg",
    "Compartment" : "images/Compartments.svg",
    "Bucket" : "images/Buckets.svg",
    "Instance" : "images/Virtual Machine.svg",
    "User" : "images/User.svg",
    "Group" : "images/User Group unisex.svg"
}

# The main one
# Subtree with types identified and counted
def makeJSSubTreeSortedByType(database, ocid):
    njson = ""

    subnode_keys = [key for key,value in database.items() if value['parent'] == ocid]
    
    typesCount = {}
    for key in subnode_keys:
        try:
            typesCount[database[key]['type']] +=1
        except:
            typesCount[database[key]['type']] = 1

    # Create subnodes for types
    for key,value in typesCount.items():
        dataItem = {}
        dataItem['node_type'] = key
        dataItem = json.dumps(dataItem)
        icon = IconChooser['Directory']
        if  key == 'Compartment':
            # Compartments type is opened by default
            opened_state = "true"
        else:
            opened_state = "false"
        
        # njson +=  '{{"id": "{}_{}", "parent": "{}", "text": "<b>{} ({})</b>", "icon":"{}", "data":{}, "state" :{{"opened":{}}}}},\n'.format(ocid, key, ocid, key, value, icon, dataItem,opened_state)
        njson +=  '{{"id": "{}_{}", "parent": "{}", "text": "<b>{} ({})</b>", "data":{}, "state" :{{"opened":{}}}}},\n'.format(ocid, key, ocid, key, value, dataItem,opened_state)
        


    # Create subnodes sorted in each type
    for key in subnode_keys:
        dataItem = json.dumps(makeJSTreeDataItem(database, key))
        icon = IconChooser.get(database[key]['type'],DefaultIcon)

        njson +=  '{{"id": "{}", "parent": "{}_{}", "text": "<b>{}</b>", "icon":"{}", "data" : {}}},\n'.format(key, ocid, database[key]['type'], database[key]['display_name'], icon, dataItem)
        # recursion

        if database[key]["type"] == 'Compartment':
            njson += makeJSSubTreeSortedByType(database, key)

    return njson

# "Flat subtree consolidated by type"
def allsubnodes_keys(database, ocid):
    subnode_keys = [key for key,value in database.items() if value['parent'] == ocid]
    toReturn = subnode_keys
    for key in subnode_keys:
        toReturn += allsubnodes_keys(database, key)
    return toReturn

def makeJSSubTreeConsolidatedByType(database, ocid):

    json = ""
    all_keys = allsubnodes_keys(database,ocid)
    typesCount = {}
    for key in all_keys :
        try:
            typesCount[database[key]['type']] +=1
        except:
            typesCount[database[key]['type']] = 1

    for key,value in typesCount.items():
        json +=  '{{"id": "{}_{}", "parent": "{}", "text": "<b>{} ({})</b>"}},\n'.format(ocid, key, ocid, key, value)

    for key in all_keys:
        json +=  '{{"id": "{}", "parent": "{}_{}", "text": "<b>{}</b>"}},\n'.format(key, ocid, database[key]['type'], database[key]['display_name'])

    return json


# Start of the script
print("Querying OCI and making up internal database (can be long !) ..", end='')
sys.stdout.flush()

# build the database of OCI objects
database = {}
fillDatabase(database, compartmentId)
print(".")

if debugFiles :
    save2File(str(database),"database.debug")

# build the json tree for html display
json = makeJSTree(database, compartmentId)

# the [] are there for use by javascript
print("Writing the data.json file to {}".format(output_location))
save2File("[" + json + "]", output_location)

# exit gracefully
exit(0)