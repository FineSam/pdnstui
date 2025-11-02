#!/usr/bin/env python3
"""
PowerDNS TUI Manager
A terminal user interface for managing PowerDNS servers and zones.

Usage:
    python pdns_tui.py --url https://pdns.example.com:8081 --api-key YOUR_KEY
    python pdns_tui.py --config config.yaml
"""

import argparse
import sys
from typing import List, Dict, Optional
from datetime import datetime

import yaml
from powerdns import PDNSApiClient, PDNSEndpoint, RRSet
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, DataTable, Input, Button, Static, Label,
    Select, TextArea, TabbedContent, TabPane
)
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.message import Message
from textual import events


class Config:
    """Configuration handler for PowerDNS connections."""
    
    def __init__(self, config_data: Dict = None, url: str = None, api_key: str = None):
        self.servers = []
        
        if config_data:
            # Load from YAML config
            for server in config_data.get('servers', []):
                self.servers.append({
                    'name': server.get('name', 'Unnamed Server'),
                    'url': server['url'],
                    'api_key': server['api_key']
                })
        elif url and api_key:
            # Single server from CLI args
            self.servers.append({
                'name': 'Default Server',
                'url': url,
                'api_key': api_key
            })
    
    @classmethod
    def from_file(cls, filepath: str):
        """Load configuration from YAML file."""
        with open(filepath, 'r') as f:
            config_data = yaml.safe_load(f)
        return cls(config_data=config_data)
    
    @classmethod
    def from_args(cls, url: str, api_key: str):
        """Create configuration from command line arguments."""
        return cls(url=url, api_key=api_key)


class PDNSManager:
    """Wrapper for PowerDNS API operations."""
    
    def __init__(self, url: str, api_key: str, name: str = "Default"):
        self.name = name
        self.url = url
        self.api_key = api_key
        self.client = None
        self.api = None
        self.api_server = None
        self.connected = False
        
        # Extract FQDN from URL for display
        from urllib.parse import urlparse
        parsed = urlparse(url)
        self.fqdn = parsed.hostname or parsed.netloc or url
        
    def connect(self):
        """Establish connection to PowerDNS API."""
        try:
            # Ensure URL has /api/v1 suffix if not present
            api_url = self.url
            if not api_url.endswith('/api/v1'):
                if api_url.endswith('/'):
                    api_url = api_url + 'api/v1'
                else:
                    api_url = api_url + '/api/v1'
            
            self.client = PDNSApiClient(api_endpoint=api_url, api_key=self.api_key)
            self.api = PDNSEndpoint(self.client)
            # Get the first server (usually there's only one)
            if self.api.servers:
                self.api_server = self.api.servers[0]
                self.connected = True
                return True
            else:
                raise Exception("No servers found")
        except Exception as e:
            self.connected = False
            raise Exception(f"Failed to connect to {self.name}: {str(e)}")
        return False
    
    def get_zones(self):
        """Retrieve all zones from the server."""
        if not self.connected:
            self.connect()
        try:
            return self.api_server.zones
        except Exception as e:
            raise Exception(f"Failed to get zones: {str(e)}")
    
    def get_zone(self, zone_id: str):
        """Get a specific zone by ID."""
        if not self.connected:
            self.connect()
        return self.api_server.get_zone(zone_id)
    
    def create_zone(self, name: str, kind: str = "Native", nameservers: List[str] = None):
        """Create a new zone."""
        if not self.connected:
            self.connect()
        try:
            # Create a basic SOA record
            from datetime import date
            serial = date.today().strftime("%Y%m%d00")
            soa_content = f"ns1.{name} hostmaster.{name} {serial} 28800 7200 604800 86400"
            soa_r = RRSet(name=name, rtype="SOA", records=[(soa_content, False)], ttl=86400)
            
            return self.api_server.create_zone(
                name=name,
                kind=kind,
                rrsets=[soa_r],
                nameservers=nameservers or []
            )
        except Exception as e:
            raise Exception(f"Failed to create zone: {str(e)}")
    
    def delete_zone(self, zone_id: str):
        """Delete a zone."""
        if not self.connected:
            self.connect()
        try:
            self.api_server.delete_zone(zone_id)
            return True
        except Exception as e:
            raise Exception(f"Failed to delete zone: {str(e)}")


class CreateZoneModal(ModalScreen[Dict]):
    """Modal dialog for creating a new zone."""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, managers: List[PDNSManager]):
        super().__init__()
        self.managers = managers
    
    def compose(self) -> ComposeResult:
        with Container(id="create-zone-dialog"):
            yield Static("Create New Zone", classes="dialog-title")
            
            # Only show server selection if multiple servers
            if len(self.managers) > 1:
                yield Label("Select Server:")
                yield Select(
                    [(f"{m.name} ({m.fqdn})", str(i)) for i, m in enumerate(self.managers)],
                    id="server-select"
                )
            
            yield Label("Zone Name (FQDN):")
            yield Input(placeholder="example.com.", id="zone-name")
            yield Label("Zone Type:")
            yield Select([
                ("Native", "Native"),
                ("Master", "Master"),
                ("Slave", "Slave"),
            ], value="Native", id="zone-kind")
            yield Label("Nameservers (comma-separated, optional):")
            yield Input(placeholder="ns1.example.com., ns2.example.com.", id="nameservers")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            name = self.query_one("#zone-name", Input).value.strip()
            kind = self.query_one("#zone-kind", Select).value
            ns_input = self.query_one("#nameservers", Input).value.strip()
            
            if not name:
                self.notify("Zone name is required", severity="error")
                return
            
            nameservers = [ns.strip() for ns in ns_input.split(",") if ns.strip()]
            
            result = {
                "name": name,
                "kind": kind,
                "nameservers": nameservers
            }
            
            # Add server index if multiple servers
            if len(self.managers) > 1:
                server_idx = self.query_one("#server-select", Select).value
                result["server_idx"] = int(server_idx)
            else:
                result["server_idx"] = 0
            
            self.dismiss(result)
        else:
            self.dismiss(None)
    
    def action_cancel(self) -> None:
        self.dismiss(None)


class CreateRecordModal(ModalScreen[Dict]):
    """Modal dialog for creating a new DNS record."""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, zone_name: str):
        super().__init__()
        self.zone_name = zone_name
    
    def compose(self) -> ComposeResult:
        with Container(id="create-record-dialog"):
            yield Static(f"Create New Record in {self.zone_name}", classes="dialog-title")
            yield Label("Record Name:")
            yield Input(placeholder="www", id="record-name")
            yield Label("Record Type:")
            yield Select([
                ("A", "A"),
                ("AAAA", "AAAA"),
                ("CNAME", "CNAME"),
                ("MX", "MX"),
                ("TXT", "TXT"),
                ("NS", "NS"),
                ("SRV", "SRV"),
                ("PTR", "PTR"),
            ], value="A", id="record-type")
            yield Label("Content:")
            yield TextArea(id="record-content")
            yield Label("TTL (seconds):")
            yield Input(placeholder="3600", value="3600", id="record-ttl")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            name = self.query_one("#record-name", Input).value.strip()
            rtype = self.query_one("#record-type", Select).value
            content = self.query_one("#record-content", TextArea).text.strip()
            ttl_str = self.query_one("#record-ttl", Input).value.strip()
            
            if not name or not content:
                self.notify("Name and content are required", severity="error")
                return
            
            try:
                ttl = int(ttl_str)
            except ValueError:
                self.notify("TTL must be a number", severity="error")
                return
            
            self.dismiss({
                "name": name,
                "type": rtype,
                "content": content,
                "ttl": ttl
            })
        else:
            self.dismiss(None)
    
    def action_cancel(self) -> None:
        self.dismiss(None)


class EditRecordModal(ModalScreen[Dict]):
    """Modal dialog for editing an existing DNS record."""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, zone_name: str, record: Dict):
        super().__init__()
        self.zone_name = zone_name
        self.record = record
    
    def compose(self) -> ComposeResult:
        with Container(id="edit-record-dialog"):
            yield Static(f"Edit Record in {self.zone_name}", classes="dialog-title")
            yield Label(f"Record Name: {self.record['name']}")
            yield Label(f"Record Type: {self.record['type']}")
            yield Label("Content:")
            yield TextArea(self.record.get('content', ''), id="record-content")
            yield Label("TTL (seconds):")
            yield Input(value=str(self.record.get('ttl', 3600)), id="record-ttl")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            content = self.query_one("#record-content", TextArea).text.strip()
            ttl_str = self.query_one("#record-ttl", Input).value.strip()
            
            if not content:
                self.notify("Content is required", severity="error")
                return
            
            try:
                ttl = int(ttl_str)
            except ValueError:
                self.notify("TTL must be a number", severity="error")
                return
            
            self.dismiss({
                "content": content,
                "ttl": ttl
            })
        else:
            self.dismiss(None)
    
    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Modal dialog for confirmation."""
    
    def __init__(self, message: str):
        super().__init__()
        self.message = message
    
    def compose(self) -> ComposeResult:
        with Container(id="confirm-dialog"):
            yield Static("Confirm Action", classes="dialog-title")
            yield Static(self.message)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Yes", variant="error", id="yes-btn")
                yield Button("No", variant="default", id="no-btn")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")


class ZoneDetailsScreen(Screen):
    """Screen showing DNS records for a specific zone."""
    
    BINDINGS = [
        ("escape", "back", "Back to zones"),
        ("c", "create_record", "Create record"),
        ("d", "delete_record", "Delete record"),
        ("e", "edit_record", "Edit record"),
        ("r", "refresh", "Refresh"),
        ("slash", "search", "Search"),
    ]
    
    def __init__(self, manager: PDNSManager, zone_id: str, zone_name: str):
        super().__init__()
        self.manager = manager
        self.zone_id = zone_id
        self.zone_name = zone_name
        self.zone = None
        self.all_records = []
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield Static(f"Zone: {self.zone_name}", id="zone-title")
            yield Input(placeholder="Search records...", id="record-search")
            yield DataTable(id="records-table")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#records-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Name", "Type", "Content", "TTL", "Disabled")
        self.load_records()
    
    def load_records(self):
        """Load all DNS records for the zone."""
        try:
            self.zone = self.manager.get_zone(self.zone_id)
            table = self.query_one("#records-table", DataTable)
            table.clear()
            
            self.all_records = []
            
            for rrset in self.zone.details.get('rrsets', []):
                name = rrset.get('name', '')
                rtype = rrset.get('type', '')
                
                for record in rrset.get('records', []):
                    content = record.get('content', '')
                    disabled = record.get('disabled', False)
                    
                    self.all_records.append({
                        'name': name,
                        'type': rtype,
                        'content': content,
                        'ttl': rrset.get('ttl', 3600),
                        'disabled': disabled,
                        'rrset': rrset
                    })
                    
                    table.add_row(
                        name,
                        rtype,
                        content[:50] + "..." if len(content) > 50 else content,
                        str(rrset.get('ttl', '')),
                        "Yes" if disabled else "No"
                    )
            
            self.notify(f"Loaded {len(self.all_records)} records")
        except Exception as e:
            self.notify(f"Error loading records: {str(e)}", severity="error")
    
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "record-search":
            self.filter_records(event.value)
    
    def filter_records(self, search_term: str):
        """Filter records based on search term."""
        table = self.query_one("#records-table", DataTable)
        table.clear()
        
        search_lower = search_term.lower()
        
        for record in self.all_records:
            if (search_lower in record['name'].lower() or
                search_lower in record['type'].lower() or
                search_lower in record['content'].lower()):
                table.add_row(
                    record['name'],
                    record['type'],
                    record['content'][:50] + "..." if len(record['content']) > 50 else record['content'],
                    str(record['ttl']),
                    "Yes" if record['disabled'] else "No"
                )
    
    def action_back(self) -> None:
        self.app.pop_screen()
        # Refresh the zones screen when we go back
        zones_screen = self.app.screen
        if isinstance(zones_screen, ZonesScreen):
            zones_screen.load_zones()
    
    def action_refresh(self) -> None:
        self.load_records()
    
    def action_search(self) -> None:
        self.query_one("#record-search", Input).focus()
    
    def action_create_record(self) -> None:
        self.app.push_screen(CreateRecordModal(self.zone_name), callback=self.on_create_record_result)
    
    def on_create_record_result(self, result) -> None:
        if result:
            try:
                # Add the record to the zone
                zone = self.manager.get_zone(self.zone_id)
                full_name = f"{result['name']}.{self.zone_name}" if result['name'] else self.zone_name
                if not full_name.endswith('.'):
                    full_name += '.'
                
                # Create RRSet for the new record
                rrset = RRSet(
                    name=full_name,
                    rtype=result['type'],
                    records=[(result['content'], False)],
                    ttl=result['ttl']
                )
                zone.create_records([rrset])
                
                self.notify(f"Record created successfully", severity="information")
                self.load_records()
            except Exception as e:
                self.notify(f"Error creating record: {str(e)}", severity="error")
    
    def action_edit_record(self) -> None:
        table = self.query_one("#records-table", DataTable)
        if table.cursor_row < 0:
            self.notify("Please select a record to edit", severity="warning")
            return
        
        record = self.all_records[table.cursor_row]
        self.app.push_screen(
            EditRecordModal(self.zone_name, record),
            callback=lambda result: self.on_edit_record_result(result, record)
        )
    
    def on_edit_record_result(self, result, record) -> None:
        if result:
            try:
                zone = self.manager.get_zone(self.zone_id)
                rrset = RRSet(
                    name=record['name'],
                    rtype=record['type'],
                    records=[(result['content'], record['disabled'])],
                    ttl=result['ttl']
                )
                zone.create_records([rrset])
                
                self.notify(f"Record updated successfully", severity="information")
                self.load_records()
            except Exception as e:
                self.notify(f"Error updating record: {str(e)}", severity="error")
    
    def action_delete_record(self) -> None:
        table = self.query_one("#records-table", DataTable)
        if table.cursor_row < 0:
            self.notify("Please select a record to delete", severity="warning")
            return
        
        record = self.all_records[table.cursor_row]
        self.app.push_screen(
            ConfirmModal(f"Delete record {record['name']} ({record['type']})?"),
            callback=lambda confirmed: self.on_delete_record_result(confirmed, record)
        )
    
    def on_delete_record_result(self, confirmed, record) -> None:
        if confirmed:
            try:
                zone = self.manager.get_zone(self.zone_id)
                rrset = RRSet(
                    name=record['name'],
                    rtype=record['type'],
                    records=[]
                )
                zone.delete_records([rrset])
                
                self.notify(f"Record deleted successfully", severity="information")
                self.load_records()
            except Exception as e:
                self.notify(f"Error deleting record: {str(e)}", severity="error")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Button handling removed - use keyboard shortcuts instead
        pass


class ZonesScreen(Screen):
    """Main screen showing all zones from all configured servers."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "create_zone", "Create zone"),
        ("d", "delete_zone", "Delete zone"),
        ("r", "refresh", "Refresh"),
        ("slash", "search", "Search"),
    ]
    
    def __init__(self, managers: List[PDNSManager]):
        super().__init__()
        self.managers = managers
        self.all_zones = []
    
    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield Static("PowerDNS Zone Manager", id="app-title")
            yield Input(placeholder="Search zones...", id="zone-search")
            yield DataTable(id="zones-table")
            yield Static("Press Enter to view zone records | c: Create | d: Delete | r: Refresh | /: Search | q: Quit", 
                        id="help-text")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#zones-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Server", "FQDN", "Zone", "Kind", "Serial", "Records", "Notified Serial")
        self.load_zones()
    
    def load_zones(self):
        """Load all zones from all configured servers."""
        table = self.query_one("#zones-table", DataTable)
        table.clear()
        self.all_zones = []
        
        for manager in self.managers:
            try:
                zones = manager.get_zones()
                for zone in zones:
                    zone_data = {
                        'manager': manager,
                        'id': zone.name,
                        'name': zone.name,
                        'kind': zone.details.get('kind', 'N/A'),
                        'serial': zone.details.get('serial', 'N/A'),
                        'records': len(zone.details.get('rrsets', [])),
                        'notified_serial': zone.details.get('notified_serial', 'N/A')
                    }
                    self.all_zones.append(zone_data)
                    
                    table.add_row(
                        manager.name,
                        manager.fqdn,
                        zone.name,
                        zone_data['kind'],
                        str(zone_data['serial']),
                        str(zone_data['records']),
                        str(zone_data['notified_serial'])
                    )
            except Exception as e:
                self.notify(f"Error loading zones from {manager.name}: {str(e)}", severity="error")
        
        self.notify(f"Loaded {len(self.all_zones)} zones from {len(self.managers)} server(s)")
    
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "zone-search":
            self.filter_zones(event.value)
    
    def filter_zones(self, search_term: str):
        """Filter zones based on search term."""
        table = self.query_one("#zones-table", DataTable)
        table.clear()
        
        search_lower = search_term.lower()
        
        for zone in self.all_zones:
            if (search_lower in zone['name'].lower() or
                search_lower in zone['kind'].lower() or
                search_lower in zone['manager'].name.lower() or
                search_lower in zone['manager'].fqdn.lower()):
                table.add_row(
                    zone['manager'].name,
                    zone['manager'].fqdn,
                    zone['name'],
                    zone['kind'],
                    str(zone['serial']),
                    str(zone['records']),
                    str(zone['notified_serial'])
                )
    
    def action_refresh(self) -> None:
        self.load_zones()
    
    def action_search(self) -> None:
        self.query_one("#zone-search", Input).focus()
    
    def action_create_zone(self) -> None:
        self.app.push_screen(CreateZoneModal(self.managers), callback=self.on_create_zone_result)
    
    def on_create_zone_result(self, result) -> None:
        if result:
            try:
                manager = self.managers[result['server_idx']]
                manager.create_zone(
                    name=result['name'],
                    kind=result['kind'],
                    nameservers=result['nameservers']
                )
                self.notify(f"Zone {result['name']} created successfully on {manager.name}", severity="information")
                self.load_zones()
            except Exception as e:
                self.notify(f"Error creating zone: {str(e)}", severity="error")
    
    def action_delete_zone(self) -> None:
        table = self.query_one("#zones-table", DataTable)
        if table.cursor_row < 0:
            self.notify("Please select a zone to delete", severity="warning")
            return
        
        zone = self.all_zones[table.cursor_row]
        self.app.push_screen(
            ConfirmModal(f"Delete zone {zone['name']}?"),
            callback=lambda confirmed: self.on_delete_zone_result(confirmed, zone)
        )
    
    def on_delete_zone_result(self, confirmed, zone) -> None:
        if confirmed:
            try:
                zone['manager'].delete_zone(zone['id'])
                self.notify(f"Zone {zone['name']} deleted successfully", severity="information")
                self.load_zones()
            except Exception as e:
                self.notify(f"Error deleting zone: {str(e)}", severity="error")
    
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        zone = self.all_zones[event.cursor_row]
        self.app.push_screen(
            ZoneDetailsScreen(zone['manager'], zone['id'], zone['name'])
        )
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Button handling removed - use keyboard shortcuts instead
        pass


class PowerDNSTUI(App):
    """PowerDNS TUI Application."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #app-title {
        text-align: center;
        color: #1f77b4;
        text-style: bold;
        padding: 1;
        background: $boost;
    }
    
    #zone-title {
        text-align: center;
        color: #1f77b4;
        text-style: bold;
        padding: 1;
        background: $boost;
    }
    
    #help-text {
        text-align: center;
        padding: 1;
        color: $text-muted;
        background: $panel;
    }
    
    DataTable {
        height: 1fr;
        background: $surface;
    }
    
    DataTable > .datatable--header {
        background: #1f77b4;
        color: $text;
        text-style: bold;
    }
    
    DataTable > .datatable--cursor {
        background: #5da5da;
        color: $text;
    }
    
    DataTable:focus > .datatable--cursor {
        background: #1f77b4;
        color: white;
    }
    
    Input {
        margin: 1 2;
        border: solid #1f77b4;
    }
    
    Input:focus {
        border: solid #5da5da;
    }
    
    #create-zone-dialog, #create-record-dialog, #edit-record-dialog, #confirm-dialog {
        width: 60;
        height: auto;
        background: $surface;
        border: thick #1f77b4;
        padding: 1 2;
    }
    
    .dialog-title {
        text-align: center;
        color: #1f77b4;
        text-style: bold;
        padding-bottom: 1;
        background: $boost;
    }
    
    .dialog-buttons {
        height: auto;
        padding-top: 1;
        align: center middle;
    }
    
    .dialog-buttons Button {
        margin: 0 1;
    }
    
    Button {
        background: #1f77b4;
        color: white;
    }
    
    Button:hover {
        background: #5da5da;
    }
    
    Button.-primary {
        background: #1f77b4;
        color: white;
        text-style: bold;
    }
    
    Button.-primary:hover {
        background: #5da5da;
    }
    
    Button.-error {
        background: #e74c3c;
        color: white;
    }
    
    Button.-error:hover {
        background: #c0392b;
    }
    
    Label {
        padding: 1 0 0 0;
        color: #1f77b4;
    }
    
    TextArea {
        height: 5;
        margin: 0 0 1 0;
        border: solid #1f77b4;
    }
    
    TextArea:focus {
        border: solid #5da5da;
    }
    
    Select {
        border: solid #1f77b4;
    }
    
    Select:focus {
        border: solid #5da5da;
    }
    
    Header {
        background: #1f77b4;
        color: white;
    }
    
    Footer {
        background: #1f77b4;
        color: white;
    }
    
    Footer > .footer--highlight {
        background: #5da5da;
    }
    
    Footer > .footer--key {
        background: #2980b9;
        color: white;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]
    
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.managers = []
    
    def on_mount(self) -> None:
        """Initialize managers and connect to servers."""
        try:
            for server in self.config.servers:
                try:
                    manager = PDNSManager(
                        url=server['url'],
                        api_key=server['api_key'],
                        name=server['name']
                    )
                    manager.connect()
                    self.managers.append(manager)
                    self.notify(f"Connected to {server['name']}", severity="information")
                except Exception as e:
                    self.notify(f"Failed to connect to {server['name']}: {str(e)}", severity="error")
                    # Continue trying other servers instead of exiting
            
            if not self.managers:
                self.notify("No servers connected. Please check your configuration.", severity="error")
                # Don't exit immediately, let user see the error
                return
            
            self.push_screen(ZonesScreen(self.managers))
        except Exception as e:
            self.notify(f"Error during initialization: {str(e)}", severity="error")


def main():
    parser = argparse.ArgumentParser(description="PowerDNS TUI Manager")
    parser.add_argument("--url", help="PowerDNS API URL")
    parser.add_argument("--api-key", help="PowerDNS API key")
    parser.add_argument("--config", help="Path to YAML configuration file")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    
    try:
        if args.config:
            try:
                config = Config.from_file(args.config)
            except Exception as e:
                print(f"Error loading configuration file: {e}")
                sys.exit(1)
        elif args.url and args.api_key:
            config = Config.from_args(args.url, args.api_key)
        else:
            parser.print_help()
            print("\nError: Either provide --config or both --url and --api-key")
            sys.exit(1)
        
        app = PowerDNSTUI(config)
        app.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
