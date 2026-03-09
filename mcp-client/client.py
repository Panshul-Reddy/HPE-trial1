import asyncio
import random
from mcp import ClientSession
from mcp.client.sse import sse_client

async def simulate_developer_session(server_url):
    print(f"\n[+] Initiating new MCP Session to {server_url}...")
    try:
        # Connect to the local proxy (plaintext), which forwards to the secure server
        async with sse_client(server_url) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("[+] Session Connected. Executing tool calls...")
                
                queries_in_session = random.randint(3, 8)
                
                for i in range(queries_in_session):
                    think_time = random.uniform(1.0, 4.0)
                    await asyncio.sleep(think_time)
                    
                    limit = random.randint(10, 5000)
                    print(f"    -> Executing query_logs (Limit: {limit}) [{i+1}/{queries_in_session}]")
                    
                    await session.call_tool("query_logs", arguments={"limit": limit})
                    
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                    
                print("[+] Developer session complete. Tearing down connection.")
                
    except Exception as e:
        print(f"[-] Session interrupted: {e}")

async def main():
    # Point the client to the local socat proxy
    server_url = "http://127.0.0.1:8080/sse"
    
    while True:
        await simulate_developer_session(server_url)
        
        idle_time = random.uniform(2.0, 5.0)
        print(f"[*] Idling for {idle_time:.1f} seconds before next session...\n")
        await asyncio.sleep(idle_time)

if __name__ == "__main__":
    asyncio.run(main())