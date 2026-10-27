#!/usr/bin/env python3
"""Minimal local MCP stdio service: assigned analysis checkpoint writes only."""
import json
import sys
from pathlib import Path
import analysis_compact
import runner


def serve(manifest_path):
    manifest=json.loads(Path(manifest_path).read_text())
    for line in sys.stdin:
        request=json.loads(line);rid=request.get('id');method=request.get('method')
        if rid is None:continue
        try:
            if method=='initialize':
                result={'protocolVersion':request['params']['protocolVersion'],'capabilities':{'tools':{}},
                        'serverInfo':{'name':'analysis_checkpoint','version':'1'}}
            elif method=='ping':result={}
            elif method=='tools/list':
                result={'tools':[{'name':'save_records','description':'Validate and durably checkpoint the next 1–5 assigned classifications. Call repeatedly before the final response. No source or Sheet modifications. Tool ACK confirms persistence; errors may be corrected without repeating saved cases.',
                                  'inputSchema':analysis_compact.tool_schema()}]}
            elif method=='tools/call':
                if request['params']['name']!='save_records':raise ValueError('Unrecognized tool.')
                try:
                    ack=analysis_compact.checkpoint(manifest,request['params']['arguments'],runner.atomic_json)
                    result={'content':[{'type':'text','text':json.dumps(ack)}],'isError':False}
                except (ValueError,KeyError,TypeError) as exc:
                    result={'content':[{'type':'text','text':str(exc)}],'isError':True}
            else:raise ValueError('Unsupported MCP method.')
            response={'jsonrpc':'2.0','id':rid,'result':result}
        except (ValueError,KeyError,TypeError) as exc:
            response={'jsonrpc':'2.0','id':rid,'error':{'code':-32602,'message':str(exc)}}
        print(json.dumps(response),flush=True)


if __name__=='__main__':serve(sys.argv[1])
