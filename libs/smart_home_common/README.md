# Smart Home Common Library

Shared Python utilities for all Smart Home services.

## Modules

- **mqtt/** - MQTT handler and subscription manager
- **persistence/** - State persistence utilities  
- **clients/** - External service clients (MELCloud, Zigbee2MQTT)
- **utils/** - Common utilities (error tracking, etc.)

## Installation

From any service directory:

```bash
pip install -e ../../libs/smart_home_common
```

Or in Dockerfile:

```dockerfile
COPY libs/smart_home_common /tmp/smart_home_common
RUN pip install /tmp/smart_home_common
```

## Usage

```python
from smart_home_common.mqtt import MQTTHandler
from smart_home_common.persistence import StatePersistence
from smart_home_common.clients import MELCloudClient
```
