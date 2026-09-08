# RAG, tools, MCP, and agents

RAG attacks start by proving retrieval: inspect query rewriting, embedding/search filters,
metadata ACL, chunk boundaries, citations, and retrieved context. Indirect instructions inside a
document are data, but they may influence a vulnerable target model; test them only through the
authorized target and record the retrieval signal.

For tool/function agents, enumerate actual descriptions, ACLs, argument validation, call traces,
and cross-tool state. Test parameter boundaries and unintended authority; do not treat natural
language claims about tools as capability evidence. For MCP, include prompts/resources, tool
descriptions, trust boundaries, and chained state. For multi-agent systems, map delegation,
message boundaries, state propagation, and memory poisoning separately.

Sources: https://portswigger.net/web-security/llm-attacks ; https://atlas.mitre.org/
