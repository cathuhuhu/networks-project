import sys
from socket import *
import random
from stp import STPSegment
import threading
import math
import time


NUM_ARGS = 7

# STP TYPES
DATA = 0
ACK = 1
SYN = 2
FIN = 3

# states
CLOSED = 0
SYN_SENT = 1
EST = 2
CLOSING = 3
FIN_WAIT = 4

constant_map = {
    DATA: "DATA",
    ACK: "ACK",
    SYN: "SYN",
    FIN: "FIN"
}

MSS = 1000


# parse in args
def parse_args(args):
    sender_port = int(args[1])
    receiver_port = int(args[2])
    txt_file_send = args[3]
    max_win = int(args[4])
    rto = int(args[5])
    flp = float(args[6])
    rlp = float(args[7])

    return sender_port, receiver_port, txt_file_send, max_win, rto, flp, rlp

class Sender:       
    def __init__(self, sender_port, receiver_port, txt_file_send, max_win, rto, flp, rlp, state = CLOSED):
        # initialising parsed variables
        self.sender_port = sender_port
        self.receiver_port = receiver_port
        self.txt_file_send =  txt_file_send
        self.max_win = math.ceil(max_win / MSS) # ??
        self.rto = rto / 1000 # ??
        self.flp = flp
        self.rlp = rlp
        self.state = state
        
        self.ISN = random.randint(0, 2**16-1) # initial seqno
        self.seqno = self.ISN
        self.sock = socket(AF_INET, SOCK_DGRAM) # create socket
        self.sock.settimeout(rto)
        self.sock.bind(('127.0.01', self.sender_port))
        self.time_start = 0
        self.first = False # indicates if the very first has been sent

        # sliding window variables
        self.segments = []
        self.sent_unacked = []
        self.base = 0
        self.oldest_seg = None
        self.expected_ack = 0
        self.lock = threading.Lock()
        self.ack_received_event = threading.Event()
        self.ack_thread = threading.Thread(target=self.receive_acks)

        # timers and timeouts and dupacks
        self.timer_running = False
        self.ack_timer = None
        self.dupACK = 0

        # final log stats
        self.last_fin_seqno = 0
        self.last_ack_log = 0
        self.segs_log = 0
        self.retransmit_log = 0
        self.dupacks_log = 0
        self.drop_send_log = 0
        self.drop_ack_log = 0        

    def final_stats(self, file):
    
        final_data = self.last_fin_seqno - (self.ISN + 1)
        final_acked = self.last_ack_log - (self.ISN + 1)

        data_sent = f'Original data sent: {str(final_data).rjust(10)}\n'
        data_acked = f'Original data acked: {str(final_acked).rjust(10)}\n'
        segs_sent = f'Original segments sent: {str(self.segs_log).rjust(5)}\n'
        retransmit = f'Retransmitted segments: {str(self.retransmit_log).rjust(5)}\n'
        dupack = f'Dup acks received: {str(self.dupacks_log).rjust(10)}\n'
        drop_data = f'Data segments dropped: {str(self.drop_send_log).rjust(5)}\n'
        drop_ack = f'Ack segments dropped: {str(self.drop_ack_log).rjust(5)}'

        with open(file, 'a') as f:
            f.write("\n" + data_sent + data_acked + segs_sent)
            f.write(retransmit + dupack + drop_data + drop_ack)
    


    def send_segment(self, segment): # returns true if successfully sent
        if random.random() < self.flp: # drop packet
            self.update_logs("drp", segment)
            if segment.seg_type == DATA:
                self.drop_send_log += 1
            return False
        seg_bytes = segment.serialise()
        self.sock.sendto(seg_bytes, ('127.0.0.1', self.receiver_port))
        return True
    
    def receive_segment(self):
        seg_bytes, _ = self.sock.recvfrom(MSS)
        rcvd_seg = STPSegment.deserialise(seg_bytes)
        if random.random() < self.rlp: # drop packet
            self.update_logs("drp", rcvd_seg)
            self.drop_ack_log += 1
            return None
        return rcvd_seg

    def receive_synack(self): # for establishing the connection
        try: 
            self.sock.settimeout(self.rto)
            rcvd_ack = self.receive_segment()
            if rcvd_ack == None:
                # raise timeout
                return None
            if rcvd_ack.seg_type == ACK:
                self.update_logs("rcv", rcvd_ack)
                return rcvd_ack
        except timeout:
            # print("Timeout for ACK, resending SYN")
            self.state = CLOSED
            return None
        
    def receive_finack(self): # for establishing the connection
        try: 
            self.sock.settimeout(self.rto)
            rcvd_ack = self.receive_segment()
            if rcvd_ack == None:
                return None
            if rcvd_ack.seg_type == ACK and rcvd_ack.seqno == self.expected_ack + 1:
                self.update_logs("rcv", rcvd_ack)
                return rcvd_ack
        except timeout:
            # print("Timeout for ACK, resending FIN")
            self.state = CLOSING
            return None
            
    def update_logs(self, action, segment):
        seqno_str = str(segment.seqno)
        seg_type = constant_map.get(segment.seg_type, "Unknown")
        
        no_bytes = str(len(segment.data))
        t = time.time()
        t_take = (t - self.time_start) * 1000
        time_str =  f"{t_take:.2f}"

        log_str = f'{action.ljust(5)} {time_str.ljust(10)} {seg_type.ljust(5)} {seqno_str.ljust(5)} {no_bytes.ljust(5)}\n'

        f = open("Sender_log.txt", "a+")
        f.write(log_str)
        f.close()
   
    # reads file and creates segments to send
    def create_segments(self):
        f = open(self.txt_file_send, 'rb')
        file_data = f.read()
        seqno = (self.ISN + 1) % 2**16

        for i in range(0, len(file_data), MSS):
            data = file_data[i:i+MSS]
            new_seqno = (seqno + len(data)) % 2**16
            segment = STPSegment(DATA, seqno, data)
            self.segments.append(segment)
            seqno = new_seqno
        self.oldest_seg = self.segments[self.base]
        self.expected_ack = (self.oldest_seg.seqno + len(self.oldest_seg.data)) % 2**16

    def receive_acks(self):
        while 1:
            rcvd_ack = self.receive_segment() # wait to receive an segment
            if rcvd_ack == None or rcvd_ack.seg_type != ACK:
                continue
            self.lock.acquire()
            if rcvd_ack.seqno >= self.expected_ack:
                # check if this is the ack for the oldest unacked segment
                self.update_logs("rcv", rcvd_ack)

                if rcvd_ack.seqno == self.expected_ack:
                    self.sent_unacked.remove(self.oldest_seg) # remove from sent unacked list
                    self.base += 1 # slide the window   
                elif rcvd_ack.seqno > self.expected_ack: # deal with cumulitive acks
                    # change base to index of rcvd_acks seqno segment in segments
                    self.base = self.get_base(rcvd_ack.seqno)
                    # go through sent unacked and remove the segments that have smaller seqno than the rcvd_ack.seqno
                    self.sent_unacked = [seg for seg in self.sent_unacked if seg.seqno >= rcvd_ack.seqno]

                # reach end of segments -> all data sent, clean thread stuff and exit
                if self.base >= len(self.segments) and len(self.sent_unacked) == 0:
                    self.last_ack_log = rcvd_ack.seqno 
                    self.lock.release() 
                    self.stop_timer()
                    self.ack_received_event.set()
                    return
                
                self.oldest_seg = self.segments[self.base] # update the oldest segment to the next unsent segment
                self.expected_ack = (self.oldest_seg.seqno + len(self.oldest_seg.data)) % 2**16 # update the expected ack aswell
                self.ack_received_event.set() # unblock

                if len(self.sent_unacked) == 0: 
                    self.stop_timer()
            else:
                self.handle_dupack(rcvd_ack) # otherwise check if its a duplicated ACK
            self.lock.release()
    
    def get_base(self, seqno):
        i = self.base
        while i < len(self.segments):
            if self.segments[i].seqno == seqno:
                return i
            i += 1

    def sliding_window(self, segments):
        win_i = 0 # window index
        self.oldest_seg = segments[self.base] # keep track of oldest unacked seg and expected ack
        self.expected_ack = (self.oldest_seg.seqno + len(self.oldest_seg.data)) % 2**16

        while self.base < len(segments): # iterate through all segments
            # sending segments within the window
            while win_i < min(self.base + self.max_win, len(segments)):
                self.lock.acquire()
                win_i = max(win_i, self.base)
                seg = segments[win_i]               
                if seg not in self.sent_unacked: # if sent but not acked, send and add to sent unacked list
                    if self.send_segment(seg):
                        self.update_logs("snd", seg)
                    self.segs_log += 1
                    self.sent_unacked.append(seg)
                    
                    if not self.timer_running: 
                        self.start_timer()  # start timer for timeout
                
                win_i += 1
                self.lock.release()
            # wait for an ack or timeout
            self.ack_received_event.wait()        
            self.ack_received_event.clear() 


    def handle_dupack(self, ack):
        if ack.seqno == self.oldest_seg.seqno:
            self.dupacks_log += 1
            self.dupACK += 1
            if self.dupACK == 3: # if 3 dupacks, resend the oldest segment
                if self.send_segment(self.oldest_seg):
                    self.retransmit_log += 1
                    self.update_logs("snd", self.oldest_seg)
                self.dupACK = 0 # reset dupack count

    def start_timer(self):
        # start a new thread that runs the timer
        self.timer_running = True
        self.ack_timer = threading.Timer(self.rto, self.handle_timeout)
        self.ack_timer.start()

    def stop_timer(self):
        if self.timer_running:
            self.ack_timer.cancel()
            self.timer_running = False

    def handle_timeout(self):
        if self.send_segment(self.oldest_seg):
            self.update_logs("snd", self.oldest_seg)
            self.retransmit_log += 1
        self.start_timer()


def main():
    sender_port, receiver_port, txt_file_send,\
        max_win, rto, flp, rlp = parse_args(sys.argv)

    f_log = open("Sender_log.txt", "w")
    f_log.close()
    
    sender = Sender(sender_port, receiver_port, txt_file_send, max_win, rto, flp, rlp)
    random.seed()
    
    # ESTABLISHING CONNECTION
    while 1:
        if sender.state == CLOSED:
            try:
                seg = STPSegment(SYN, sender.ISN,'') # create syn packet
                if not sender.first:
                    sender.time_start = time.time()
                    sender.first = True
                if sender.send_segment(seg): # send packet to rcv
                    sender.update_logs("snd", seg)                
            except Exception as e:
                sys.exit(f"Failed to start connection")
            sender.state = SYN_SENT
        if sender.state == SYN_SENT:
            r_ack_seg = sender.receive_synack()
            if r_ack_seg != None:  
                # print("Connection established")
                sender.seqno = (sender.seqno + 1) % 2**16
                sender.state = EST
                
    
        # SENDING DATA
        if sender.state == EST:
            sender.sock.settimeout(None)
            sender.create_segments()
            # starts receiving acks in a separate thread
            sender.ack_thread.start()

            sender.sliding_window(sender.segments)
            sender.state = CLOSING
        
        # CLOSING CONNECTION
        if sender.state == CLOSING:
            try:
                sender.last_fin_seqno = sender.expected_ack
                seg = STPSegment(FIN, sender.expected_ack,'') # create fin packet
                if sender.send_segment(seg): # send packet to rcv
                    sender.update_logs("snd", seg)
                sender.state = FIN_WAIT
            except Exception as e:
                sys.exit(f"Failed to send fin packet")
        if sender.state == FIN_WAIT:
            r_ack_seg = sender.receive_finack()
            if r_ack_seg != None:                 
                sender.state = CLOSED
                sender.sock.close()
                break

    sender.final_stats(f_log.name)
                
            

if __name__ == '__main__':
    sys.exit(main())

