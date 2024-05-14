# run on top of udp

import sys
from socket import *
from stp import STPSegment
import time
import math
import threading

NUM_ARGS = 4

# STP TYPES
DATA = 0
ACK = 1
SYN = 2
FIN = 3

# states
CLOSED = 0
LISTEN = 1
EST = 2
TIME_WAIT = 3

constant_map = {
    DATA: "DATA",
    ACK: "ACK",
    SYN: "SYN",
    FIN: "FIN"
}

MSS = 1000
MSL = 1 # second

# parse in args
def parse_args(args):
    receiver_port = int(args[1])
    sender_port = int(args[2])
    txt_file_rcvd = args[3]
    max_win = int(args[4])

    return receiver_port, sender_port, txt_file_rcvd, max_win


class Receiver:
    def __init__(self, receiver_port, sender_port, txt_file_rcvd, max_win, state = CLOSED):

        self.sender_port = sender_port
        self.receiver_port = receiver_port
        self.txt_file_rcvd =  txt_file_rcvd
        self.max_win = math.ceil(max_win /  MSS)
        self.state = state

        self.sock = socket(AF_INET, SOCK_DGRAM) # create socket
        self.time_start = 0
        self.timer = threading.Timer(2 * MSL, self.to_closed_state)
        self.close_started = False
        self.first = False # indicates if the very first has been sent

        self.received_seqnos = set()

        # buffer variables
        self.buffer = []
        self.expected = 0

        # log
        self.last_fin_seqno = 0
        self.first_ack = 0
        self.segs_log = 0
        self.dupdata_log = 0
        self.dupacks_log = 0
    
    def send_segment(self, segment):
        seg_bytes = segment.serialise()
        self.sock.sendto(seg_bytes, ('localhost', self.sender_port))
        self.update_logs("snd", segment)
    
    def receive_segment(self):
        try:
            seg_bytes, _ = self.sock.recvfrom(MSS + 4)
        except Exception as e:
            sys.exit(f"Failed to get segment")
        rcvd_seg = STPSegment.deserialise(seg_bytes)
        
        return rcvd_seg
    
    # update the logs
    def update_logs(self, action, segment):
        seqno_str = str(segment.seqno)
        seg_type = constant_map.get(segment.seg_type, "Unknown")
        no_bytes = str(len(segment.data))

        t = time.time()
        t_take = (t - self.time_start) * 1000
        time_str =  f"{t_take:.2f}"

        log_str = f'{action.ljust(5)} {time_str.ljust(10)} {seg_type.ljust(5)} {seqno_str.ljust(5)} {no_bytes.ljust(5)}\n'

        f = open("Receiver_log.txt", "a+")
        f.write(log_str)
        f.close()

    # add data seg to buffer
    def buffer_data(self, seg):
        if len(self.buffer) < self.max_win:
            self.buffer.append(seg)
            self.buffer.sort(key=lambda x: x.seqno, reverse=True)

    # write data to file, update the next expected seqno, send ack
    def write_and_send(self, file, data_seg):
        file.write(data_seg.data)
        self.received_seqnos.add(data_seg.seqno)
        self.expected = (data_seg.seqno + len(data_seg.data)) % 2**16
        ack = STPSegment(ACK, self.expected, '')
        self.send_segment(ack)
        self.segs_log += 1

    # check if any packets in the buffer can be sent and send them
    def check_buffer(self, file):
        for i in range(len(self.buffer) - 1, -1, -1):
            seg = self.buffer[i]
            if seg.seqno == self.expected:
                self.write_and_send(file, seg)
                self.buffer.remove(seg)

    def to_closed_state(self):
        self.sock.close()
        self.timer.cancel()
        self.state = CLOSED
        # sys.exit(0)

    def final_stats(self, file):
        final_data = self.last_fin_seqno - self.first_ack

        data_rcv = f'Original data received: {str(final_data).rjust(10)}\n'
        segs_rcv = f'Original segments received: {str(self.segs_log).rjust(5)}\n'
        dup_data = f'Dup data segments received: {str(self.dupdata_log).rjust(5)}\n'
        dupack = f'Dup ack segments sent: {str(self.dupacks_log).rjust(10)}\n'
        
        with open(file, 'a') as f:
            f.write("\n" + data_rcv + segs_rcv + dup_data + dupack)


def main():
    receiver_port, sender_port, txt_file_rcvd, max_win = parse_args(sys.argv)
    f_log = open("Receiver_log.txt", "w")
    f_log.close()

    f = open(txt_file_rcvd, 'wb')

    receiver = Receiver(receiver_port, sender_port, txt_file_rcvd, max_win)
    receiver.sock.bind(('127.0.0.1', receiver_port))

    receiver.state = LISTEN

    while 1:
        # CONNECTION SETUP #
        if receiver.state == LISTEN:
            # print("receiver listening for segments")
            try:
                rcvd_segment = receiver.receive_segment()
                if not receiver.first:
                    receiver.time_start = time.time()
                    receiver.first = True
            except Exception as e:
                sys.exit(f"Failed to get segment")

            receiver.update_logs("rcv", rcvd_segment)

            if rcvd_segment.seg_type == SYN:
                new_seqno = (rcvd_segment.seqno + 1) % 2**16
                connection_ack = STPSegment(ACK, new_seqno, '')
                receiver.first_ack = new_seqno # for log
                receiver.expected = new_seqno 
                receiver.send_segment(connection_ack)
                receiver.state = EST
        
        # START RECEIVING AND WRITING DATA #
        if receiver.state == EST:
            data_seg = receiver.receive_segment()
            receiver.update_logs("rcv", data_seg)

            if data_seg.seg_type == SYN: # if its a resend of syn
                receiver.state = LISTEN
            if data_seg.seg_type == FIN:
                receiver.last_fin_seqno = data_seg.seqno
                receiver.state = TIME_WAIT
                receiver.expected += 1
                
            if data_seg.seqno == receiver.expected:
                # if its expected
                receiver.write_and_send(f, data_seg)
                receiver.check_buffer(f)
            elif data_seg.seqno > receiver.expected:
                # if its out of order, buffer the data
                receiver.buffer_data(data_seg)
            elif data_seg.seqno < receiver.expected: # if its a duplicate
                # check if seqno is in, send dupack
                if data_seg.seqno in receiver.received_seqnos:
                    dup_ack = STPSegment(ACK, receiver.expected, '')
                    receiver.send_segment(dup_ack)
                    receiver.dupdata_log += 1
                    receiver.dupacks_log += 1
                

        # CONNECTION TEARDOWN #
        if receiver.state == TIME_WAIT:
            # create thread for timer to close program
            if not receiver.close_started:
                receiver.close_started = True
                receiver.timer.start()
                # 
                finack = STPSegment(ACK, receiver.expected, '')
                receiver.send_segment(finack)

        if receiver.state == CLOSED:
            break
    
    receiver.final_stats(f_log.name)
                
        
     

if __name__ == '__main__':
    sys.exit(main())
