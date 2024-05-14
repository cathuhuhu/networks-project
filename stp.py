import sys

class STPSegment:
    def __init__(self, seg_type, seqno, data = None):

        self.seg_type = seg_type # DATA, ACK, SYN, FIN
        self.seqno = seqno 
        self.data = data

    # for debugging
    def print_segment_info(self, s):
        print(f'({s}) seg type: {str(self.seg_type)}  /  seqno: {str(self.seqno)}  /  data size = {str(len(self.data))}')

    def serialise(self):
        # turns stp segments into bytes to be encapsulated and sent
        try:
            seg_type_bytes = self.seg_type.to_bytes(2, byteorder="big")
            seqno_bytes = self.seqno.to_bytes(2, byteorder="big")
            data_bytes = self.data if self.data else b""
        except Exception as e:
            sys.exit(f"failed to serialise")

        return seg_type_bytes + seqno_bytes + data_bytes
    
    @classmethod
    def deserialise(cls, data):
        try:
            seg_type = int.from_bytes(data[:2], byteorder="big")
            seqno = int.from_bytes(data[2:4], byteorder="big")
            seg_data = data[4:]
        except Exception as e:
            sys.exit(f"failed to deserialise")
        
        return cls(seg_type, seqno, seg_data)
