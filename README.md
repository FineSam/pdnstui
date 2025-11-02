# PowerDNS TUI Manager

A terminal user interface (TUI) for managing PowerDNS servers and zones, built with Python and the Textual framework.

## Features

- **Multi-Server Management:** Connect to and manage multiple PowerDNS servers from a single interface.
- **Zone Management:**
    - List all zones from all configured servers.
    - Search and filter the zone list.
    - Create new zones.
    - Delete existing zones.
- **Record Management:**
    - View all records for a specific zone.
    - Search and filter records within a zone.
    - Create, edit, and delete DNS records (A, AAAA, CNAME, MX, TXT, etc.).
- **User-Friendly Interface:**
    - Modal dialogs for creating and editing zones and records.
    - Confirmation prompts for destructive actions.
    - Helpful keybindings for quick navigation and actions.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd pdnstui
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install the dependencies:**
    ```bash
    pip install textual powerdns pyyaml
    ```

## Usage

There are two ways to run the application:

### 1. Using a Configuration File (Recommended)

Create a `config.yaml` file with your PowerDNS server details. This is the most convenient way to manage multiple servers.

**Example `config.yaml`:**

```yaml
servers:
  - name: "Primary DNS"
    url: "https://pdns.example.com:8081"
    api_key: "your_primary_api_key"
  - name: "Secondary DNS"
    url: "https://pdns-secondary.example.com:8081"
    api_key: "your_secondary_api_key"
```

Then, run the application:

```bash
python pdnstui.py --config config.yaml
```

### 2. Using Command-Line Arguments

For a single server, you can provide the URL and API key directly as arguments.

```bash
python pdnstui.py --url https://pdns.example.com:8081 --api-key YOUR_KEY
```

## Keybindings

### Main (Zones) Screen

| Key     | Action                |
|---------|-----------------------|
| `Enter` | View records for the selected zone |
| `c`     | Create a new zone     |
| `d`     | Delete the selected zone |
| `r`     | Refresh the list of zones |
| `/`     | Focus the search input  |
| `q`     | Quit the application    |

### Zone Details (Records) Screen

| Key      | Action                |
|----------|-----------------------|
| `Escape` | Go back to the zones list |
| `c`      | Create a new record   |
| `d`      | Delete the selected record |
| `e`      | Edit the selected record |
| `r`      | Refresh the list of records |
| `/`      | Focus the search input  |

## License

This project is licensed under the MIT License.
