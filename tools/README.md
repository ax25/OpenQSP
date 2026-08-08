# Tools

`frame_tool.py HEX` decodes a canonical Core frame and prints its typed fields.
Set `PYTHONPATH=server/src` when running directly from a checkout.

The interactive reference TCP client is `python -m openqsp.client.cli`. It sends
messages without UUIDs or application retry identifiers and expects the
zero-payload `STORED` response. Historical retry/conflict scenarios were removed
because retry identity now belongs to unreliable transport adapters, not Core.
