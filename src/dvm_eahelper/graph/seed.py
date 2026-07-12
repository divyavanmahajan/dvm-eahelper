"""
Seed script for the Application Capability Map graph database.

Graph model:
  (Application)-[:SUPPORTS]->(BusinessCapability)
  (Application)-[:EXPOSES]->(Interface)-[:CONSUMED_BY]->(Application)
  (Interface)-[:CARRIES]->(DataObject)
"""

from __future__ import annotations

from dvm_eahelper.graph.base import GraphBackend

BUSINESS_CAPABILITIES = [
    {"id": "bc-customer-mgmt", "name": "Customer Management", "description": "Manage customer lifecycle, profiles and segmentation"},
    {"id": "bc-order-mgmt", "name": "Order Management", "description": "Create, fulfil and track customer orders"},
    {"id": "bc-finance", "name": "Financial Management", "description": "Accounts payable/receivable, general ledger, reporting"},
    {"id": "bc-inventory", "name": "Inventory Management", "description": "Track stock levels, warehousing and replenishment"},
    {"id": "bc-hr", "name": "Human Resources", "description": "Employee records, payroll and workforce planning"},
    {"id": "bc-analytics", "name": "Analytics & Reporting", "description": "Business intelligence and operational dashboards"},
]

APPLICATIONS = [
    {"id": "app-crm", "name": "CRM System", "description": "Customer relationship management", "technology": "Salesforce"},
    {"id": "app-erp", "name": "ERP System", "description": "Enterprise resource planning", "technology": "SAP"},
    {"id": "app-oms", "name": "Order Management System", "description": "Order capture and fulfilment", "technology": "Custom Java"},
    {"id": "app-wms", "name": "Warehouse Management System", "description": "Inventory and warehouse ops", "technology": "Manhattan WMS"},
    {"id": "app-hrms", "name": "HR Management System", "description": "HR, payroll and workforce", "technology": "Workday"},
    {"id": "app-bi", "name": "BI Platform", "description": "Analytics and dashboards", "technology": "Power BI"},
    {"id": "app-ecomm", "name": "E-Commerce Platform", "description": "Online storefront and cart", "technology": "Shopify"},
    {"id": "app-mdm", "name": "Master Data Hub", "description": "Master data management and distribution", "technology": "Informatica MDM"},
]

# (source_app_id, target_app_id, interface_name, protocol, data_object_name, data_object_description)
INTERFACES = [
    ("app-crm", "app-mdm", "Customer Master Sync", "REST", "Customer", "Customer profile including contact details and segmentation"),
    ("app-mdm", "app-erp", "Customer Distribution", "REST", "Customer", "Customer profile including contact details and segmentation"),
    ("app-mdm", "app-oms", "Customer Distribution", "REST", "Customer", "Customer profile including contact details and segmentation"),
    ("app-ecomm", "app-oms", "Order Submission", "REST", "Order", "Order header, lines, quantities and delivery details"),
    ("app-oms", "app-erp", "Order Financials", "REST", "Order", "Order header, lines, quantities and delivery details"),
    ("app-oms", "app-wms", "Fulfilment Request", "Message", "FulfilmentOrder", "Pick/pack instructions derived from a sales order"),
    ("app-wms", "app-oms", "Shipment Confirmation", "Message", "Shipment", "Despatch advice with tracking details"),
    ("app-wms", "app-erp", "Stock Valuation", "Batch", "StockPosition", "Warehouse stock on-hand quantities and values"),
    ("app-erp", "app-bi", "Financial Extract", "Batch", "FinancialData", "GL transactions, cost centres and P&L entries"),
    ("app-hrms", "app-erp", "Payroll Journal", "Batch", "PayrollEntry", "Payroll cost allocations for financial posting"),
    ("app-hrms", "app-bi", "Workforce Metrics", "Batch", "EmployeeData", "Headcount, attrition and workforce KPIs"),
]

# (app_id, capability_id)
APP_CAPABILITIES = [
    ("app-crm", "bc-customer-mgmt"),
    ("app-erp", "bc-customer-mgmt"),
    ("app-erp", "bc-order-mgmt"),
    ("app-erp", "bc-finance"),
    ("app-erp", "bc-inventory"),
    ("app-oms", "bc-order-mgmt"),
    ("app-wms", "bc-inventory"),
    ("app-hrms", "bc-hr"),
    ("app-bi", "bc-analytics"),
    ("app-ecomm", "bc-order-mgmt"),
    ("app-ecomm", "bc-customer-mgmt"),
    ("app-mdm", "bc-customer-mgmt"),
]


def _relation_rows(links: list[tuple[str, str]], rel_name: str) -> list[dict]:
    return [{"source_id": src, "relation": rel_name, "target_id": tgt} for src, tgt in links]


def seed(backend: GraphBackend) -> None:
    interface_records = []
    data_object_records = {}
    interface_relations = []
    for idx, (src, tgt, iface_name, protocol, do_name, do_desc) in enumerate(INTERFACES):
        iface_id = f"iface-{idx:03d}"
        interface_records.append({"id": iface_id, "name": iface_name, "protocol": protocol})
        data_object_records[do_name] = {"id": do_name, "name": do_name, "description": do_desc}
        interface_relations.append({"source_id": src, "relation": "relApplicationToInterface", "target_id": iface_id})
        interface_relations.append({"source_id": iface_id, "relation": "relInterfaceToApplication", "target_id": tgt})
        interface_relations.append({"source_id": iface_id, "relation": "relInterfaceToDataObject", "target_id": do_name})

    rel_map = {
        "relApplicationToInterface": "EXPOSES",
        "relInterfaceToApplication": "CONSUMED_BY",
        "relInterfaceToDataObject": "CARRIES",
        "relApplicationToBusinessCapability": "SUPPORTS",
    }

    with backend:
        print(f"[{backend.__class__.__name__}] Connected.")

        print("Clearing existing data...")
        backend.clear()

        print("Ensuring schema...")
        backend.ensure_schema(
            ["Application", "BusinessCapability", "Interface", "DataObject"],
            [
                ("SUPPORTS", "Application", "BusinessCapability"),
                ("EXPOSES", "Application", "Interface"),
                ("CONSUMED_BY", "Interface", "Application"),
                ("CARRIES", "Interface", "DataObject"),
            ],
        )

        print("Creating BusinessCapability nodes...")
        backend.upsert_nodes("BusinessCapability", BUSINESS_CAPABILITIES)

        print("Creating Application nodes...")
        backend.upsert_nodes("Application", APPLICATIONS)

        print("Creating Interface nodes...")
        backend.upsert_nodes("Interface", interface_records)

        print("Creating DataObject nodes...")
        backend.upsert_nodes("DataObject", list(data_object_records.values()))

        print("Creating SUPPORTS relationships...")
        backend.upsert_relationships(_relation_rows(APP_CAPABILITIES, "relApplicationToBusinessCapability"), rel_map)

        print("Creating Interface relationships...")
        backend.upsert_relationships(interface_relations, rel_map)

        print("\nSeed complete. Summary:")
        stats = backend.query_stats()
        for label in ["Application", "BusinessCapability", "Interface", "DataObject"]:
            print(f"  {label}: {stats.get(label, 0)}")
        print(f"  Relationships: {stats.get('_relationships', 0)}")
