# buid local
/bin/python3 ./oci-web1.py --compartment_id ocid1.compartment.oc1..aaaaaaaagun5fvcvwpz2zlvjpgi5l4rysluy33rba2v5mfyqkube5expi2za
or
/bin/python3 ./oci-web1.py 
(will run on the full tenant)

# test local
cd /home/evinck/Documents/OCI-Commander/apache2_conf
source envvars
apache2 -d /home/evinck/Documents/OCI-Commander/apache2_conf -k start
xdg-open http://localhost:8080/


# build docker image
docker build -t oci-companion .

# test cli
docker run -it oci-companion /bin/bash

# run
docker run -it --mount type=bind,source=$HOME/.oci,destination=/root/.oci -p 8080:8080 oci-companion --compartment_id ocid1.compartment.oc1..aaaaaaaagun5fvcvwpz2zlvjpgi5l4rysluy33rba2v5mfyqkube5expi2za


# au début on demandera que la key_file soit dans ~/.oci
# et référencée comme ~/.oci
# et on n'utilisera que le profile "default"
# idée => éventuellement créer une entrée exprès pour l'outil
