


/bin/python3 /home/evinck/Documents/OCI-Commander/oci-web1/oci-web1.py ocid1.compartment.oc1..aaaaaaaagun5fvcvwpz2zlvjpgi5l4rysluy33rba2v5mfyqkube5expi2za
ou
/bin/python3 ./oci-web1.py ocid1.tenancy.oc1..aaaaaaaafipe4lmow7rfrn5f3egpg3xgur6v2q2wgvb3id4ehwujnpu5mb5q


# test local
cd /home/evinck/Documents/OCI-Commander/apache2_conf
source envvars
apache2 -d /home/evinck/Documents/OCI-Commander/apache2_conf -k start
http://localhost:8080/

# test remote
scp index.html data.json opc@130.162.219.19:/var/www/html
http://130.162.219.19:80
osc/pwd4OSC#



