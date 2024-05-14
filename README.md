# networks-project
Simplified TCP over UDP
- Meant to be run locally on the same machine
- 2-way connection setup (SYN, ACK) – sender initiated
- Sender chooses a random ISN in the range of 0 to 216-1
- 2-way connection termination (FIN, ACK) – sender initiated
- Sender maintains a single timer and retransmits the oldest unacknowledged segment if timer expires
- Receiver buffers out of order segments
- Fast retransmit
