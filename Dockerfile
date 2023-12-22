FROM python:3.10-alpine

WORKDIR /controller
RUN apk add libcap
COPY requirements.txt ./
RUN pip install -r "requirements.txt"
COPY requirements.txt controller/ ./
# python interpreter needs NET_ADMIN privileges to alter routes on the host
RUN setcap 'cap_net_admin+ep' $(readlink -f $(which python))
USER 405
ENTRYPOINT [ "kopf", "run", "--all-namespaces", "--verbose", "static-route-handler.py"]
