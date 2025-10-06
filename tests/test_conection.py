from azure.storage.blob import BlobServiceClient
import os

# Script para probar si un blob existe y listar blobs en un contenedor

conn = os.environ["TEST_STORAGE_CONNECTION_STRING"]
container = os.environ["TEST_STORAGE_CONTAINER"]
project = os.environ["TEST_PROJECT_ID"].strip("/")
blob_rel = os.environ["TEST_TARGET_BLOB"].strip("/")
blob_name = f"{project}/{blob_rel}"

client = BlobServiceClient.from_connection_string(conn)
blob_client = client.get_blob_client(container, blob_name)
print(blob_name, "exists?", blob_client.exists())


client = BlobServiceClient.from_connection_string(conn)
container_client = client.get_container_client(container)

for blob in container_client.list_blobs(name_starts_with=f"{project}/raw/"):
    print(blob.name)

