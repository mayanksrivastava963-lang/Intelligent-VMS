# Multiple isolated camera partitions

Provision one extracted release per dedicated server. Run setup independently,
then select a resource profile. Merge one node's non-secret values below into its
private installation configuration; supply separate database users/passwords,
certificates, approved camera CIDRs and a firewall-approved bind address.

Node A:

```dotenv
COMPOSE_PROJECT_NAME=vms-site-a
POSTGRES_DB=vms_site_a
VMS_RECORDING_VOLUME=vms-site-a-recordings
VMS_REDIS_VOLUME=vms-site-a-redis
VMS_CONTROL_SUBNET=172.30.85.0/24
```

Node B:

```dotenv
COMPOSE_PROJECT_NAME=vms-site-b
POSTGRES_DB=vms_site_b
VMS_RECORDING_VOLUME=vms-site-b-recordings
VMS_REDIS_VOLUME=vms-site-b-redis
VMS_CONTROL_SUBNET=172.30.87.0/24
```

Assign a camera to one partition only. Use separate HTTPS hostnames. A central
external PostgreSQL server can host the distinct databases if connection, IO and
backup capacity are qualified. These examples contain no customer secrets and
create/delete no databases themselves. Database provisioning is administrator work.

This is partitioned deployment, not a federated single dashboard or shared-database
HA cluster. Multiple recorder replicas on one database are intentionally rejected.
The multi-server topology requires validation on actual servers; it has not been
load-tested or certified on this laptop. See the resource/scaling guide for gates.
