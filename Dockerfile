FROM python
LABEL oci-companion=alpha
RUN apt-get update
RUN pip install oci
RUN mkdir /root/DocumentRoot
RUN mkdir /root/DocumentRoot/images
COPY DocumentRoot/index.html /root/DocumentRoot
COPY DocumentRoot/styles.css /root/DocumentRoot
COPY DocumentRoot/images/* /root/DocumentRoot/images/
COPY oci-web1.py /root 
COPY start.sh /root
RUN chmod u+rx /root/start.sh
ENTRYPOINT ["/root/start.sh"]