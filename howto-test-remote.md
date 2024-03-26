# test remote
http://oci-companion.osc-cloud.com/
osc/pwd4OSC#

# remote deploy
scp ../DocumentRoot/index.html opc@oci-companion.osc-cloud.com:/home/opc/DocumentRoot/
scp -pr ../DocumentRoot/images opc@oci-companion.osc-cloud.com:/home/opc/DocumentRoot/images
scp oci-web1.py opc@oci-companion.osc-cloud.com:/home/opc


[opc@oci-web1-811893 ~]$ time python3 ./oci-web1.py
No compartment specified, will go for the whole tenancy (can be long !).
Generating the json file (can be long !) ..................................................................................................................................................
........................................................................................................................................
Writing the data.json file...

real    24m44.302s
user    0m36.882s
sys     0m1.533s

