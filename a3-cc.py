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

class Receiver:
    def __init__(self):
        # TODO: Initialize any variables you want here, like the receive
        # buffer, initial congestion window and initial values for the timeout
        # values
        self.buffer = {}
        self.expected_seq = 0

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[List[Tuple[int, int]], str]:
        '''This function is called whenever a data packet is
        received. `seq_range` is the range of sequence numbers
        received: It contains two numbers: the starting sequence
        number (inclusive) and ending sequence number (exclusive) of
        the data received. `data` is a binary string of length
        `seq_range[1] - seq_range[0]` representing the data.

        It should output the list of sequence number ranges to
        acknowledge and any data that is ready to be sent to the
        application. Note, data must be sent to the application
        _reliably_ and _in order_ of the sequence numbers. This means
        that if bytes in sequence numbers 0-10000 and 11000-15000 have
        been received, only 0-10000 must be sent to the application,
        since if we send the latter bytes, we will not be able to send
        bytes 10000-11000 in order when they arrive. The transport
        layer must hide hide all packet reordering and loss.

        The ultimate behavior of the program should be that the data
        sent by the sender should be stored exactly in the same order
        at the receiver in a file in the same directory. No gaps, no
        reordering. You may assume that our test cases only ever send
        printable ASCII characters (letters, numbers, punctuation,
        newline etc), so that terminal output can be used to debug the
        program.

        '''

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

        # 從buffer裡面拿資料
        ready_data = ""
        while self.expected_seq in self.buffer:
            packet = self.buffer[self.expected_seq]
            ready_data += packet
            del self.buffer[self.expected_seq]
            self.expected_seq += len(packet)

        # 合併所有已收到的區間
        keys = sorted(self.buffer.keys())
        ranges = []
        last_start = None
        last_end = None
        # 先把已 deliver 的區間加進去
        if self.expected_seq > 0:
            ranges.append((0, self.expected_seq))
        for k in keys:
            seg_len = len(self.buffer[k])
            if last_end is None or k > last_end:
                # 新區間
                last_start = k
                last_end = k + seg_len
                ranges.append((last_start, last_end))
            else:
                # 連續區間合併
                last_end = max(last_end, k + seg_len)
                ranges[-1] = (last_start, last_end)
        return ranges, ready_data

    def finish(self):
        '''Called when the sender sends the `fin` packet. You don't need to do
        anything in particular here. You can use it to check that all
        data has already been sent to the application at this
        point. If not, there is a bug in the code. A real transport
        stack will deallocate the receive buffer. Note, this may not
        be called if the fin packet from the sender is locked. You can
        read up on "TCP connection termination" to know more about how
        TCP handles this.

        '''

        # TODO
        if self.buffer:
            print("Not all data was sent to the application. There might be an issue.")
        else:
            print("All data was successfully received and delivered.")

class Sender:
    def __init__(self, data_len: int):
        '''`data_len` is the length of the data we want to send. A real
        transport will not force the application to pre-commit to the
        length of data, but we are ok with it.

        '''
        # TODO: Initialize any variables you want here, for instance a
        # data structure to keep track of which packets have been
        # sent, acknowledged, detected to be lost or retransmitted
        self.data_len = data_len # The total amount of data
        self.next_seq = 0  # The sequence number of the next byte to send
        self.acknowledged = set()  # Set of acknowledged sequence numbers
        self.unacknowledged = set()  # Set of unacknowledged sequence numbers
        self.dup_ack_count = {}
        self.cumulative_sacks = []
        self.last_ack_id_seen = {}
        self.done = False
        self.highest_sack = 0  # 記錄目前收到的最大 ACK 結尾
        
        self.cwnd = payload_size
        self.send_time = {}
        self.estimated_rtt = 1.0
        self.dev_rtt = 0.0
        self.alpha = 1 / 64
        self.beta = 1 / 4
        self.rto = 1.0
        self.state = "slow_start"
        self.ssthresh = 64000
        self.retransmit_queue = []



    def timeout(self):
        '''Called when the sender times out.'''
        # TODO: In addition to what you did in assignment 1, set cwnd to 1
        # packet
        ''' Called when the sender times out and needs to retransmit '''
        if self.next_seq >= self.data_len and not self.unacknowledged:
            self.done = True  #通知主程式傳送真的結束
            return

        if self.unacknowledged:
            # timeout 時選擇最早未被 ack 的封包重傳
            self.next_seq = min(self.unacknowledged)

            # 觸發 AIMD 的 multiplicative decrease
            self.cwnd = max(payload_size, self.cwnd / 2)

           
            self.ssthresh = max(self.cwnd / 2, payload_size)
            self.cwnd = payload_size  # = 1 MSS
            self.state = "slow_start"  
            self.dup_ack_count.clear()  
            print(f"[TIMEOUT] Retransmit from seq {self.next_seq}, cwnd reset to {self.cwnd}, ssthresh = {self.ssthresh}")


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
                    
                    if self.state == "slow_start":
                        self.cwnd += payload_size
                        self.dup_ack_count.clear()
                        # 若超過 ssthresh，就轉換到 congestion_avoidance
                        if self.cwnd >= self.ssthresh:
                            self.state = "congestion_avoidance"
                            print(f"[Exit Slow Start] cwnd = {self.cwnd:.2f}, ssthresh = {self.ssthresh:.2f}")
                    elif self.state == "congestion_avoidance":
                        self.cwnd += (payload_size * payload_size) / self.cwnd

                # 根據 packet_id 更新 RTT 與 RTO
                if packet_id in self.send_time:
                    sample_rtt = time.time() - self.send_time[packet_id]
                    self.estimated_rtt = (1 - self.alpha) * self.estimated_rtt + self.alpha * sample_rtt
                    self.dev_rtt = (1 - self.beta) * self.dev_rtt + self.beta * abs(sample_rtt - self.estimated_rtt)
                    self.rto = self.estimated_rtt + 4 * self.dev_rtt
                    del self.send_time[packet_id]

                self.dup_ack_count.pop(seq, None)
                self.last_ack_id_seen[seq] = packet_id

            if not sacks:
                return new_acknowledged

        base_seq = min(start for start, _ in sacks)
        retransmit_ranges = []

        for seq in list(self.unacknowledged):
            # 只處理 base_seq 前的封包
            if seq >= base_seq:
                continue

            in_sack = any(start <= seq < end for start, end in sacks)
            if not in_sack:
                if self.last_ack_id_seen.get(seq) != packet_id:
                    self.dup_ack_count[seq] = self.dup_ack_count.get(seq, 0) + 1
                    self.last_ack_id_seen[seq] = packet_id
                    
                    if self.state == "fast_recovery":
                        self.cwnd += payload_size


                    if self.dup_ack_count[seq] == 3 and self.state != "fast_recovery":
                        self.ssthresh = self.cwnd / 2
                        self.cwnd = self.ssthresh + 3 * payload_size
                        self.state = "fast_recovery"
                        self.recovery_seq = max(end for _, end in sacks)
                        print("[Fast Recovery] Entered, cwnd =", self.cwnd)
                        retransmit_ranges.append((seq, seq + payload_size))

            else:
                self.dup_ack_count.pop(seq, None)
                self.last_ack_id_seen[seq] = packet_id

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

        # 合併 retransmit 區段
        retransmit_ranges.sort()
        merged = []
        for start, end in retransmit_ranges:
            if not merged or merged[-1][1] < start:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))

        for start, end in merged:
            print(f"DUP retransmit Sending seq: ({start}, {end})")
        self.retransmit_queue.extend(merged)


        if sacks:
            self.highest_sack = max(self.highest_sack, max(end for _, end in sacks))
            
        
        print(f"[ACK] Updated cwnd = {self.cwnd:.2f}, rto = {self.rto:.4f}")
        
        # 判斷是否收到 new ACK 結束 fast recovery
        if self.state == "fast_recovery":
            new_highest = max(end for _, end in sacks)
            if new_highest >= self.recovery_seq:
                self.dup_ack_count.clear()
                self.highest_sack = new_highest
                self.cwnd = self.ssthresh
                self.state = "congestion_avoidance"
                print(f"[Fast Recovery Exit] cwnd reset to ssthresh = {self.cwnd}")




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
        if self.retransmit_queue:
            start, end = self.retransmit_queue.pop(0)
            if start not in self.acknowledged:
                self.unacknowledged.add(start)
                return (start, end)
        
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
    `Receiver` class. When a `fin` packet is received, we call the
    `finish` function of that class.

    We start listening on the given IP address and port. By setting
    the IP address to be `0.0.0.0`, you can make it listen on all
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

    Virtual interfaces also exist. The most common one is `localhost',
    which has the default IP address of `127.0.0.1` (a universal
    constant across most machines). The Mahimahi network emulator also
    creates virtual interfaces that behave like real interfaces, but
    really only emulate a network link in software that shuttles
    packets between different virtual interfaces.

    '''

    receivers: Dict[str, Receiver] = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((ip, port))

        while True:
            print("======= Waiting =======")
            data, addr = server_socket.recvfrom(packet_size)
            if addr not in receivers:
                receivers[addr] = Receiver()

            received = json.loads(data.decode())
            if received["type"] == "data":
                # Format check. Real code will have much more
                # carefully designed checks to defend against
                # attacks. Can you think of ways to exploit this
                # transport layer and cause problems at the receiver?
                # This is just for fun. It is not required as part of
                # the assignment.
                assert type(received["seq"]) is list
                assert type(received["seq"][0]) is int and type(received["seq"][1]) is int
                assert type(received["payload"]) is str
                assert len(received["payload"]) <= payload_size

                # Deserialize the packet. Real transport layers use
                # more efficient and standardized ways of packing the
                # data. One option is to use protobufs (look it up)
                # instead of json. Protobufs can automatically design
                # a byte structure given the data structure. However,
                # for an internet standard, we usually want something
                # more custom and hand-designed.
                sacks, app_data = receivers[addr].data_packet(tuple(received["seq"]), received["payload"])
                # Note: we immediately write the data to file
                #receivers[addr][1].write(app_data)

                # Send the ACK
                server_socket.sendto(json.dumps({"type": "ack", "sacks": sacks, "id": received["id"]}).encode(), addr)


            elif received["type"] == "fin":
                receivers[addr].finish()
                del receivers[addr]

            else:
                assert False

def start_sender(ip: str, port: int, data: str, recv_window: int, simloss: float):
    sender = Sender(len(data))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
        # So we can receive messages
        client_socket.connect((ip, port))
        # When waiting for packets when we call receivefrom, we
        # shouldn't wait more than 500ms
        client_socket.settimeout(0.5)

        # Number of bytes that we think are inflight. We are only
        # including payload bytes here, which is different from how
        # TCP does things
        inflight = 0
        packet_id  = 0
        wait = False

        while True:
            # Get the congestion condow
            cwnd = sender.get_cwnd()
            rto = sender.get_rto()
            status = "send" if inflight + payload_size <= min(recv_window, cwnd) and not wait else "wait"

            # Do we have enough room in recv_window to send an entire
            # packet?
            if inflight + payload_size <= min(recv_window, cwnd) and not wait:
                seq = sender.send(packet_id)
                if seq is None:
                    # We are done sending
                    client_socket.send('{"type": "fin"}'.encode())
                    break
                elif seq[1] == seq[0]:
                    # No more packets to send until loss happens. Wait
                    wait = True
                    print(f"cwnd: {cwnd}, rto: {rto:.4f}, status: {status}")
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)

                # Simulate random loss before sending packets
                if random.random() < simloss:
                    print("Dropped!")
                else:
                    # Send the packet
                    sender.send_time[packet_id] = time.time()
                    client_socket.send(
                        json.dumps(
                            {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                        ).encode())

                inflight += seq[1] - seq[0]
                packet_id += 1
                print(f"Sending seq: {seq}, id: {packet_id}, cwnd: {cwnd}, rto: {rto:.4f}, status: {status}")

            else:
                wait = False
                # Wait for ACKs
                try:
                    rto = sender.get_rto()
                    client_socket.settimeout(rto)
                    received_bytes = client_socket.recv(packet_size)
                    received = json.loads(received_bytes.decode())
                    assert received["type"] == "ack"

                    if random.random() < simloss:
                        print("Dropped ack!")
                        continue

                    inflight -= sender.ack_packet(received["sacks"], received["id"])
                    assert inflight >= 0
                    print(f"Got ACK sacks: {received['sacks']}, id: {received['id']}, cwnd: {cwnd}, rto: {rto:.4f}, status: {status}")
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

    args = parser.parse_args()

    if args.role == "receiver":
        start_receiver(args.ip, args.port)
    else:
        if args.sendfile is None:
            print("No file to send")
            return

        with open(args.sendfile, 'r') as f:
            data = f.read()
            start_sender(args.ip, args.port, data, args.recv_window, args.simloss)

if __name__ == "__main__":
    main()