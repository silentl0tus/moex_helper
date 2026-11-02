#!/usr/bin/env python3
"""
Diagnostic script for Data Foundry MCP server discovery.
Connects via streamable HTTP transport, extracts tool schemas, and runs test queries.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import requests

MCP_URL = "https://mcp.vrednyj-investor.ru/mcp"
HEALTHZ_URL = "https://mcp.vrednyj-investor.ru/healthz"
DOCS_OUT = "docs/mcp_schema_reference.json"


def serialize_mcp_obj(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


async def main():
    print(f"[{datetime.now().isoformat()}] Probing Data Foundry MCP...")
    
    # Check healthz first
    try:
        hz = requests.get(HEALTHZ_URL, timeout=5).json()
        print(f"Healthz: {json.dumps(hz, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"Healthz failed: {e}")
        hz = {"error": str(e)}

    results = {
        "healthz": hz,
        "tools": {},
        "probes": {}
    }

    async with streamable_http_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Session initialized successfully.")

            # 1. List tools and input schemas
            tools_result = await session.list_tools()
            print(f"Found {len(tools_result.tools)} tools.")
            for tool in tools_result.tools:
                schema = getattr(tool, "input_schema", getattr(tool, "inputSchema", None))
                if hasattr(schema, "model_dump"):
                    schema = schema.model_dump()
                print(f"\n--- Tool: {tool.name} ---")
                print(f"Description: {tool.description}")
                print(f"Input Schema: {json.dumps(schema, indent=2, ensure_ascii=False)}")
                results["tools"][tool.name] = {
                    "description": tool.description,
                    "inputSchema": schema
                }

            # Helper for calling a tool
            async def call_tool_json(tool_name: str, args: dict):
                print(f"\n>>> Calling {tool_name} with {args}")
                res = await session.call_tool(tool_name, arguments=args)
                parsed_content = []
                for item in res.content:
                    if hasattr(item, "text"):
                        try:
                            parsed_content.append(json.loads(item.text))
                        except Exception:
                            parsed_content.append(item.text)
                    else:
                        parsed_content.append(serialize_mcp_obj(item))
                return parsed_content

            # 2. Test SBER (Banking sector)
            print("\n================== PROBING SBER (Banking) ==================")
            sber_search = await call_tool_json("search_companies", {"query_text": "SBER"})
            print(f"SBER search result: {json.dumps(sber_search, indent=2, ensure_ascii=False)}")

            sber_metrics = await call_tool_json("find_metrics", {"query_text": "прибыль", "companies": ["SBER"]})
            print(f"SBER metrics (прибыль): {json.dumps(sber_metrics, indent=2, ensure_ascii=False)}")

            sber_interest = await call_tool_json("find_metrics", {"query_text": "процентный", "companies": ["SBER"]})
            print(f"SBER metrics (процентный): {json.dumps(sber_interest, indent=2, ensure_ascii=False)}")

            sber_metric_codes = ["fin.net_income", "bank.net_interest_income", "bank.net_fee_commission_income"]

            sber_periods = ["2023-FY", "2024-H1", "2024-FY"]
            # Call coverage
            sber_coverage = await call_tool_json("get_coverage", {
                "companies": ["SBER"],
                "metrics": sber_metric_codes,
                "periods": sber_periods
            })
            print(f"SBER coverage: {json.dumps(sber_coverage, indent=2, ensure_ascii=False)}")

            # Call get_series
            sber_series = await call_tool_json("get_series", {
                "companies": ["SBER"],
                "metrics": sber_metric_codes,
                "periods": sber_periods
            })
            print(f"SBER series: {json.dumps(sber_series, indent=2, ensure_ascii=False)}")

            # Find source_ids
            sber_source_ids = []
            def extract_source_ids(data):
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k in ("source_id", "source_ids") and v:
                            if isinstance(v, list):
                                sber_source_ids.extend(v)
                            else:
                                sber_source_ids.append(v)
                        else:
                            extract_source_ids(v)
                elif isinstance(data, list):
                    for item in data:
                        extract_source_ids(item)

            extract_source_ids(sber_series)
            print(f"SBER source_ids found: {sber_source_ids}")

            sber_evidence = None
            if sber_source_ids:
                sber_evidence = await call_tool_json("get_evidence", {"source_ids": sber_source_ids[:3]})
                print(f"SBER evidence: {json.dumps(sber_evidence, indent=2, ensure_ascii=False)}")

            results["probes"]["SBER"] = {
                "search": sber_search,
                "metrics": sber_metrics,
                "interest_metrics": sber_interest,
                "coverage": sber_coverage,
                "series": sber_series,
                "evidence": sber_evidence
            }

            # 3. Test LKOH (Real sector)
            print("\n================== PROBING LKOH (Real sector) ==================")
            lkoh_search = await call_tool_json("search_companies", {"query_text": "LKOH"})
            print(f"LKOH search result: {json.dumps(lkoh_search, indent=2, ensure_ascii=False)}")

            lkoh_metrics = await call_tool_json("find_metrics", {"query_text": "выручка", "companies": ["LKOH"]})
            print(f"LKOH metrics (выручка): {json.dumps(lkoh_metrics, indent=2, ensure_ascii=False)}")

            lkoh_metric_codes = ["fin.revenue", "fin.net_income", "fin.ebitda", "fin.interest_bearing_debt"]

            lkoh_coverage = await call_tool_json("get_coverage", {
                "companies": ["LKOH"],
                "metrics": lkoh_metric_codes,
                "periods": sber_periods
            })
            print(f"LKOH coverage: {json.dumps(lkoh_coverage, indent=2, ensure_ascii=False)}")

            lkoh_series = await call_tool_json("get_series", {
                "companies": ["LKOH"],
                "metrics": lkoh_metric_codes,
                "periods": sber_periods
            })
            print(f"LKOH series: {json.dumps(lkoh_series, indent=2, ensure_ascii=False)}")

            lkoh_source_ids = []
            def extract_lkoh_source_ids(data):
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k in ("source_id", "source_ids") and v:
                            if isinstance(v, list):
                                lkoh_source_ids.extend(v)
                            else:
                                lkoh_source_ids.append(v)
                        else:
                            extract_lkoh_source_ids(v)
                elif isinstance(data, list):
                    for item in data:
                        extract_lkoh_source_ids(item)

            extract_lkoh_source_ids(lkoh_series)
            print(f"LKOH source_ids found: {lkoh_source_ids}")

            lkoh_evidence = None
            if lkoh_source_ids:
                lkoh_evidence = await call_tool_json("get_evidence", {"source_ids": lkoh_source_ids[:3]})
                print(f"LKOH evidence: {json.dumps(lkoh_evidence, indent=2, ensure_ascii=False)}")

            results["probes"]["LKOH"] = {
                "search": lkoh_search,
                "metrics": lkoh_metrics,
                "coverage": lkoh_coverage,
                "series": lkoh_series,
                "evidence": lkoh_evidence
            }

    # Save to docs
    os.makedirs(os.path.dirname(DOCS_OUT), exist_ok=True)
    with open(DOCS_OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[SUCCESS] Dumped full schema and probe results to {DOCS_OUT}")

if __name__ == "__main__":
    asyncio.run(main())
