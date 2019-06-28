'UML Sequence Diagram for pbench-agent work flow with tool meister and tool data sink. 

User -> Controller: pbench-register-tool[-set] NodeA
'Place holder to setup Controller, ToolStore, Redis, and Sink together
Controller -> ToolStore
Controller -> Redis
Controller -> Sink
'Continue with first pbench-register-tool[-set]
Controller --> NodeA: verify tool(s) [ssh] 
Controller <-- NodeA: success
note right of Controller: Verification of tools is performed via ssh asynchronously
Controller -> ToolStore: record
Controller -> User: success

User -> Controller: pbench-register-tool[-set] NodeB
Controller --> NodeB: verify tool(s) [ssh]
Controller <-- NodeB: success
Controller -> ToolStore: record
Controller -> User: success

User -> Controller: pbench-user-benchmark

Controller -> Redis: setup
note left of Redis: Redis Server\nContains all tool data for all nodes, loaded from the ToolStore\nby the controller and stored in JSON format, all tool meisters pull their\nindividual configuration from the Redis instance.\nThe Redis instance also contains the configuration for the Sink instance. 
Redis -> Controller: success

Controller -> Sink: setup
Sink -> Redis: fetch config via Redis key
Redis -> Sink: success
Sink -> Controller: success

par Setup Tool Meisters
Controller --> NodeA: pbench-tool-meister setup
Controller --> NodeB: pbench-tool-meister setup
NodeA --> Redis: fetch config via Redis key
NodeB --> Redis: fetch config via Redis key
Redis --> NodeA: success
Redis --> NodeB: success
NodeA --> Controller: success
NodeB --> Controller: success
end

Controller -> Redis: publish start tools
par Redis pub/sub mech
Redis --> NodeA: start 0-iteration
Redis --> NodeB: start 0-iteration
NodeA --> Redis: success
NodeB --> Redis: success
end
Redis -> Controller: success (start tools)

note right of Controller: Controller (pbench-user-benchmark) invokes benchmark script ...

Controller -> Redis: publish stop tools
par Redis pub/sub mech
Redis --> NodeA: stop 0-iteration
Redis --> NodeB: stop 0-iteration
NodeA --> Redis: success
NodeB --> Redis: success
end
Redis -> Controller: success (stop tools)

Controller -> Redis: publish send tools
par Redis pub/sub mech
Redis --> NodeA: send 0-iteration
Redis --> NodeB: send 0-iteration
note left of NodeA: Nodes A & B build up tar balls containing all tool data for given iteration
par HTTP PUT of tar balls
NodeA --> Sink: PUT tool(s) tar ball(s)
NodeB --> Sink: PUT tool(s) tar ball(s)
Sink --> NodeA: success
Sink --> NodeB: success
end
NodeA --> Redis: success
NodeB --> Redis: success
end
Redis -> Controller: success (send tools)

par pbench-collect-sysinfo
Controller --> NodeA: collect config
Controller --> NodeB: collect config
NodeA --> Controller: success (config tar ball)
NodeB --> Controller: success (config tar ball)
end

Controller -> User: success
User -> Controller: pbench-move-results
Controller -> Server: send result tar ball
Server -> Controller: success
Controller -> User: success
