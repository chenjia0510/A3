# Your Name: xxxx
# Your ID: Bxxxxxx

import argparse
import json
import random
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

# Note: In this starter code, we annotate types where
# appropriate. While it is optional, both in python and for this
# course, we recommend it since it makes programming easier.

# The maximum size of the data contained within one packet
payload_size = 1200
# The maximum size of a packet including all the JSON formatting
packet_size = 1500
BDP_BYTES   = 30_000


class Receiver:
    def __init__(self):
        # TODO: Initialize any variables you want here, like the receive buffer
        # Initialize a buffer to store received data until it's ready for delivery
        self.buffer = {}
        self.expected_seq = 0

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[List[Tuple[int, int]], str]:
        # TODO

        # 把這個封包存進 buffer

        # 試著把可以交付的資料送給應用層

        # 回傳目前為止有哪些資料我「確認收到」（ack_ranges）
        
        #收過了，ACK回去，不交給L7
        # 如果收到的封包有重疊（但不是完全落後），還是要存進 buffer
        if seq_range[1] <= self.expected_seq:
            return [(seq_range[0], seq_range[1])], ""  # 完全收到過的就不要再處理

        
        #不管怎樣，都先存到buffer中
        self.buffer[seq_range[0]] = data
        ack_ranges = [(seq_range[0], seq_range[1])]

        #從buffer裡面拿資料
        ready_data = ""
        while self.expected_seq in self.buffer:
            packet = self.buffer[self.expected_seq]
            ready_data += packet
            del self.buffer[self.expected_seq]
            newExpected = self.expected_seq + len(packet)
            ack_ranges.append((self.expected_seq, newExpected))
            self.expected_seq = newExpected  # Increment by the length of the current packet
        
        # Acknowledge the range of sequence numbers received
        return ack_ranges, ready_data

    def finish(self):
        # TODO
        ''' Check if all data has been sent to the application'''
        if self.buffer:
            print("Not all data was sent to the application. There might be an issue.")
        else:
            print("All data was successfully received and delivered.")

class Sender:
    def __init__(self, data_len: int, fixed_cwnd_bytes: int | None = None):
        '''`data_len` is the length of the data we want to send. A real
        transport will not force the application to pre-commit to the
        length of data, but we are ok with it.

        '''
        # TODO: Initialize any variables you want here, for instance a
        self.data_len = data_len # The total amount of data
        self.next_seq = 0  # The sequence number of the next byte to send
        self.acknowledged = set()  # Set of acknowledged sequence numbers
        self.unacknowledged = set()  # Set of unacknowledged sequence numbers
        self.cumulative_sacks = []
        self.last_ack_id_seen = {}
        self.done = False
        self.highest_sack: int = 0                      # ← 新增        

        self.send_time = {}
        self.estimated_rtt = 1.0
        self.dev_rtt = 0.0
        self.alpha = 1 / 64
        self.beta = 1 / 4
        self.rto = 1.0
        self.cwnd = fixed_cwnd_bytes
        
    def timeout(self):
        '''Called when the sender times out.'''
        # TODO: Initialize any variables you want here, for instance a
        ''' Called when the sender times out and needs to retransmit '''



    def ack_packet(self, sacks: List[Tuple[int, int]], packet_id: int) -> int:
        '''Called every time we get an acknowledgment. The argument is a list
        of ranges of bytes that have been ACKed. Returns the number of
        payload bytes new that are no longer in flight, either because
        the packet has been acked (measured by the unique ID) or it
        has been assumed to be lost because of dupACKs. Note, this
        number is incremental. For example, if one 100-byte packet is
        ACKed and another 500-byte is assumed lost, we will return
        600, even if 1000s of bytes have been ACKed before this.

        '''

        # TODO
        '''Called every time we get an acknowledgment.'''
        new_acknowledged = 0

        # 紀錄已被 ack 的封包，並清除其 dup 記錄
        for start, end in sacks:
            for seq in range(start, end, payload_size):
                actual_size = min(payload_size, end - seq)
                if seq not in self.acknowledged and seq in self.unacknowledged:
                    self.unacknowledged.remove(seq)
                    self.acknowledged.add(seq)
                    new_acknowledged += actual_size
                    
                    

                # 根據 packet_id 更新 RTT 與 RTO
                if packet_id in self.send_time:
                    sample_rtt = time.time() - self.send_time[packet_id]
                    self.estimated_rtt = (1 - self.alpha) * self.estimated_rtt + self.alpha * sample_rtt
                    self.dev_rtt = (1 - self.beta) * self.dev_rtt + self.beta * abs(sample_rtt - self.estimated_rtt)
                    self.rto = self.estimated_rtt + 4 * self.dev_rtt
                    del self.send_time[packet_id]



            if not sacks:
                return new_acknowledged

        base_seq = min(start for start, _ in sacks)

        for seq in list(self.unacknowledged):
            # 只處理 base_seq 前的封包
            if seq >= base_seq:
                continue

            in_sack = any(start <= seq < end for start, end in sacks)

                    





        # 印 cumulative SACK 狀態
        ack_list = sorted(self.acknowledged)
        merged_sacks = []
        if ack_list:
            start = ack_list[0]
            end = start + payload_size
            for seq in ack_list[1:]:
                if seq == end:
                    end += payload_size
                else:
                    merged_sacks.append([start, end])
                    start = seq
                    end = start + payload_size
            merged_sacks.append([start, end])
        print(f"Got ACK sacks: {merged_sacks}, id: {packet_id}")



        if sacks:
            self.highest_sack = max(self.highest_sack, max(end for _, end in sacks))
            
        
        print(f"[ACK] Updated cwnd = {self.cwnd:.2f}, rto = {self.rto:.4f}")
        




        return new_acknowledged

    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        '''Called just before we are going to send a data packet. Should
        return the range of sequence numbers we should send. If there
        are no more bytes to send, returns a zero range (i.e. the two
        elements of the tuple are equal). Return None if there are no
        more bytes to send, and _all_ bytes have been
        acknowledged. Note: The range should not be larger than
        `payload_size` or contain any bytes that have already been
        acknowledged

        '''

        # TODO
        # Check if we've reached the end and have no more data to send
        
        # 如果有重傳封包要送，優先送這個

        
        if self.done:
            return None 
        
        if self.next_seq >= self.data_len:
            if self.highest_sack >= self.data_len:
                self.done = True
                return None
            else:
                return (self.data_len, self.data_len)

        # Find the next Unacked seq and send it
        while self.next_seq in self.acknowledged:
            self.next_seq = min(self.next_seq + payload_size, self.data_len)
            
            
        # 防止送出已經被 ack 的區段
        if self.next_seq in self.acknowledged:
            return None    
        
        end_seq = min(self.next_seq + payload_size, self.data_len)
        self.unacknowledged.add(self.next_seq)
        seq_range = (self.next_seq, end_seq)
        self.next_seq = end_seq
        return seq_range

    def get_cwnd(self) -> int:
        # TODO
        return max(packet_size, int(self.cwnd))


    def get_rto(self) -> float:
        # TODO
        return max(0.001, self.rto)


def start_receiver(ip: str, port: int):
    '''Starts a receiver thread. For each source address, we start a new
    Receiver class. When a fin packet is received, we call the
    finish function of that class.

    We start listening on the given IP address and port. By setting
    the IP address to be 0.0.0.0, you can make it listen on all
    available interfaces. A network interface is typically a device
    connected to a computer that interfaces with the physical world to
    send/receive packets. The WiFi and ethernet cards on personal
    computers are examples of physical interfaces.

    Sometimes, when you start listening on a port and the program
    terminates incorrectly, it might not release the port
    immediately. It might take some time for the port to become
    available again, and you might get an error message saying that it
    could not bind to the desired port. In this case, just pick a
    different port. The old port will become available soon. Also,
    picking a port number below 1024 usually requires special
    permission from the OS. Pick a larger number. Numbers in the
    8000-9000 range are conventional.

    Virtual interfaces also exist. The most common one is localhost',
    which has the default IP address of 127.0.0.1 (a universal
    constant across most machines). The Mahimahi network emulator also
    creates virtual interfaces that behave like real interfaces, but
    really only emulate a network link in software that shuttles
    packets between different virtual interfaces. Use ifconfig in a
    terminal to find out what interfaces exist in your machine or
    inside a Mahimahi shell

    '''

    receivers: Dict[str, Tuple[Receiver, Any]] = {}
    received_data = ''
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((ip, port))

        while True:
            print("======= Waiting =======")
            data, addr = server_socket.recvfrom(packet_size)
            #檢查一下，是不是第一次遇到這個sender
            if addr not in receivers and json.loads(data.decode())["type"] == "data":
                #是的話，寫新的檔案，然候放進receivers的dicts裡面
                outfile = open(f'rcvd-{addr[0]}-{addr[1]}.txt', 'w')
                receivers[addr] = (Receiver(), outfile)


            received = json.loads(data.decode())
            if received["type"] == "data":

                
                #因為UDP不保證完整信，因此手動檢查
                
                #檢查是否為list
                assert type(received["seq"]) is list
                #檢查seq標示的位置是否有錯
                assert type(received["seq"][0]) is int and type(received["seq"][1]) is int
                #確定payload包字串
                assert type(received["payload"]) is str
                #檢查有沒有超過限制
                assert len(received["payload"]) <= payload_size

                sacks, app_data = receivers[addr][0].data_packet(tuple(received["seq"]), received["payload"])
                # Note: we immediately write the data to file
                receivers[addr][1].write(app_data)
                receivers[addr][1].flush() 
                print(f"Received seq: {received['seq']}, id: {received['id']}, sending sacks: {sacks}")
                received_data += app_data

                # Send the ACK
                server_socket.sendto(json.dumps({"type": "ack", "sacks": sacks, "id": received["id"]}).encode(), addr)
            elif received["type"] == "fin":
                if addr in receivers:  # 加這行避免 KeyError
                    receivers[addr][0].finish()
                    # Check if the file is received and send fin-ack
                    if received_data:
                        print("received data (summary): ", received_data[:100], "...", len(received_data))
                        print("received file is saved into: ", receivers[addr][1].name)
                        server_socket.sendto(json.dumps({"type": "fin"}).encode(), addr)
                        received_data = ''

                    
                    receivers[addr][1].close() #你加這句看看
                    del receivers[addr]

            else:
                assert False


def start_sender(ip: str, port: int, data: str, recv_window: int, simloss: float, pkts_to_reorder: int,fixed_cwnd_bytes: int):
    sender = Sender(len(data), fixed_cwnd_bytes)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
        buf_size = client_socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        print("Current socket recv buffer size:", buf_size)
        # So we can receive messages
        client_socket.connect((ip, port))
        # When waiting for packets when we call receivefrom, we
        # shouldn't wait more than 500ms
        client_socket.settimeout(0.5)

        # Number of bytes that we think are inflight. We are only
        # including payload bytes here, which is different from how
        # TCP does things
        inflight = 0
        packet_id = 0
        wait = False
        send_buf = []
        

        while True:
            # Do we have enough room in recv_window to send an entire
            # packet?
            while inflight + payload_size <= sender.get_cwnd() and not wait:
                seq = sender.send(packet_id)
                got_fin_ack = False
                if seq is None:
                    # We are done sending
                    # print("#######send_buf#########: ", len(send_buf))
                    if send_buf:
                        random.shuffle(send_buf)
                        for p in send_buf:
                            client_socket.send(p)
                        send_buf = []
                    client_socket.send('{"type": "fin"}'.encode())
                    try:
                        print("======= Final Waiting =======")
                        received = client_socket.recv(packet_size)
                        received = json.loads(received.decode())
                        if received["type"] == "ack":
                            client_socket.send('{"type": "fin"}'.encode())
                            continue
                        elif received["type"] == "fin":
                            print(f"Got FIN-ACK")
                            got_fin_ack = True
                            break
                    except socket.timeout:
                        inflight = 0
                        print("Timeout")
                        sender.timeout()
                        exit(1)
                    if got_fin_ack:
                        break
                    else:
                        continue

                elif seq[1] == seq[0]:
                    # No more packets to send until loss happens. Wait
                    wait = True
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)
                print(f"Sending seq: {seq}, id: {packet_id}")

                # Simulate random loss before sending packets
                if random.random() < simloss:
                    print("Dropped!")
                else:
                    
                    sender.send_time[packet_id] = time.time()

                    
                    pkt_str = json.dumps(
                        {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                    ).encode()
                    # pkts_to_reorder is a variable that bounds the maximum amount of reordering. To disable reordering, set to 1
                    if len(send_buf) < pkts_to_reorder:
                        send_buf += [pkt_str]

                    if len(send_buf) == pkts_to_reorder:
                        # Randomly shuffle send_buf
                        random.shuffle(send_buf)

                        for p in send_buf:
                            client_socket.send(p)
                        send_buf = []

                packet_len = seq[1] - seq[0]
                if inflight + packet_len > sender.get_cwnd():
                    wait = True
                    continue
                inflight += packet_len
                
                packet_id += 1

            else:
                wait = False
                # Wait for ACKs
                try:
                    print("======= Waiting =======")
                    received = client_socket.recv(packet_size)
                    received = json.loads(received.decode())
                    assert received["type"] == "ack"

                    # print(f"Got ACK sacks: {received['sacks']}, id: {received['id']}")
                    if random.random() < simloss:
                        print("Dropped ack!")
                        continue

                    inflight -= sender.ack_packet(received["sacks"], received["id"])
                    inflight = max(0, inflight)
                except socket.timeout:
                    inflight = 0
                    print("Timeout")
                    sender.timeout()



def main():
    parser = argparse.ArgumentParser(description="Transport assignment")
    parser.add_argument("role", choices=["sender", "receiver"], help="Role to play: 'sender' or 'receiver'")
    parser.add_argument("--ip", type=str, required=True, help="IP address to bind/connect to")
    parser.add_argument("--port", type=int, required=True, help="Port number to bind/connect to")
    parser.add_argument("--sendfile", type=str, required=False, help="If role=sender, the file that contains data to send")
    parser.add_argument("--recv_window", type=int, default=15000000, help="Receive window size in bytes")
    parser.add_argument("--simloss", type=float, default=0.0, help="Simulate packet loss. Provide the fraction of packets (0-1) that should be randomly dropped")
    parser.add_argument("--fixed_cwnd", type=int, default=1,
                        help="固定 cwnd，單位＝幾個 BDP (1 BDP = 30,000 bytes)")



    args = parser.parse_args()
    
    fixed_bytes = 30000 * args.fixed_cwnd

    if args.role == "receiver":
        start_receiver(args.ip, args.port)
    else:
        if args.sendfile is None:
            print("No file to send")
            return

        with open(args.sendfile, 'r') as f:
            data = f.read()
            start_time = time.time()
            start_sender(args.ip, args.port, data, args.recv_window, args.simloss,1,fixed_bytes)
            end_time = time.time()
            print(f"[測量時間] 傳送時間 = {end_time - start_time:.3f} 秒")


if __name__ == "__main__":
    main()