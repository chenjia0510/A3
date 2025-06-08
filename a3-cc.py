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

        # 檢查收到的封包是否是期望的下一個封包
        if seq_range[0] == self.expected_seq:
            # 如果是，則將資料傳給 application layer，並更新 expected_seq
            ready_data = data
            self.expected_seq += len(data)
            # 回傳目前為止有哪些資料我「確認收到」（ack_ranges）
            return [(0, self.expected_seq)], ready_data
        else:
            # 如果不是，則不將資料傳給 application layer，只回傳 ACK
            return [(0, self.expected_seq)], ""

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
        print("Receiver: FIN packet received.")

class Sender:
    def __init__(self, data_len: int):
        '''`data_len` is the length of the data we want to send. A real
        transport will not force the application to pre-commit to the
        length of data, but we are ok with it.

        '''
        # TODO: Initialize any variables you want here, for instance a
        # data structure to keep track of which packets have been
        # sent, acknowledged, detected to be lost or retransmitted
        self.data_len = data_len
        self.unacked_packets: Dict[int, Dict[str, Any]] = {} # {packet_id: {'seq_range': (start, end), 'sent_time': time}}
        self.next_seq_to_send = 0
        self.last_acked_seq = 0

        self.sent_time: Dict[int, float] = {} # {packet_id: sent_timestamp}
        self.estimated_rtt: float = 1.0  # Initial estimated RTT (conservative) 
        self.dev_rtt: float = 0.0
        self.alpha: float = 1/8 # Common alpha for EstimatedRTT
        self.beta: float = 1/4  # Common beta for DevRTT
        self.min_rto: float = 0.001 # Minimum RTO of 1ms 

        self.cwnd: int = packet_size # Congestion window, initialized to 1 packet 
        self.ssthresh: int = 30000   # Slow start threshold, e.g., 1 BDP 
        self.dup_acks: int = 0
        self.last_acked_id: Optional[int] = None
        self.in_fast_recovery: bool = False
        self.recovery_seq: Optional[int] = None # 紀錄進入 Fast Recovery 時的 Recovery Sequence Number
        self.inflight = 0 # 紀錄 inflight 的大小
        self.last_sacks: List[Tuple[int, int]] = []

    def timeout(self):
        '''Called when the sender times out.'''
        print("Timeout detected!")
        if not (self.cwnd == packet_size and not self.in_fast_recovery):
            print("============== 進入 slowstart (timeout)============== ")
        self.ssthresh = max(self.cwnd // 2, packet_size)
        self.cwnd = packet_size
        self.next_seq_to_send = self.last_acked_seq
        self.unacked_packets.clear()
        self.sent_time.clear()
        self.dup_acks = 0
        self.in_fast_recovery = False
        self.inflight = 0

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

        bytes_freed = 0

        # 檢查是否為重複ACK
        if self.last_acked_id is not None and packet_id == self.last_acked_id:
            self.dup_acks += 1
            if self.dup_acks == 3 and not self.in_fast_recovery:
                # Fast Retransmit: On 3rd duplicate ACK
                self.ssthresh = max(self.cwnd // 2, packet_size)
                self.cwnd = self.ssthresh + 3 * packet_size # TCP Reno specific. Adjust for this assignment.
                self.in_fast_recovery = True
                # 紀錄進入 Fast Recovery 時的 Recovery Sequence Number
                self.recovery_seq = self.next_seq_to_send
                # Re-transmit the lost packet (the one expected based on duplicate ACKs)
                # For simplicity in this assignment, we might not explicitly retransmit here
                # but rely on the timeout if necessary.
                print("============== 進入 fast recovery============== ")
            elif self.in_fast_recovery:
                self.cwnd += packet_size # Inflate window by one segment for each additional dup ACK
            return bytes_freed # No new bytes acknowledged, just duplicate ACK

        # 新的ACK
        if self.in_fast_recovery:
            print("============== 離開 fast recovery，進入 avoidence============== ")
        self.last_acked_id = packet_id
        self.dup_acks = 0
        self.in_fast_recovery = False

        # Process SACKs (Selective Acknowledgments)
        for ack_start, ack_end in sacks:
            # We assume a single packet is acknowledged by its packet_id,
            # and the `sacks` list confirms the range.
            # In a real SACK implementation, we'd go through all unacked_packets
            # and mark them as acknowledged if their sequence range is covered by any SACK.
            # For simplicity, we primarily use packet_id for RTT calculation and
            # assume the `packet_id` ACK means that packet is acknowledged.

            # Find the packet acknowledged by packet_id
            if packet_id in self.unacked_packets:
                acked_packet_info = self.unacked_packets.pop(packet_id)
                acked_seq_range = acked_packet_info['seq_range']
                bytes_freed += (acked_seq_range[1] - acked_seq_range[0])
                self.inflight -= (acked_seq_range[1] - acked_seq_range[0]) # 更新 inflight

                # Update last_acked_seq if this acknowledgment extends it
                self.last_acked_seq = max(self.last_acked_seq, acked_seq_range[1])

                # Calculate SampleRTT and update RTT estimates
                sample_rtt = time.time() - acked_packet_info['sent_time']

                # 
                # EstimatedRTT = (1 - alpha) * EstimatedRTT + alpha * SampleRTT
                self.estimated_rtt = (1 - self.alpha) * self.estimated_rtt + self.alpha * sample_rtt

                # DevRTT = (1 - beta) * DevRTT + beta * |SampleRTT - EstimatedRTT| 
                self.dev_rtt = (1 - self.beta) * self.dev_rtt + self.beta * abs(sample_rtt - self.estimated_rtt)

                # Congestion Window Adjustment (AIMD) 
                if self.cwnd < self.ssthresh:
                    # Slow Start: increase cwnd by 1 MSS (packet_size) for each ACK
                    old_cwnd = self.cwnd
                    self.cwnd += packet_size
                    # 如果加完剛好跨過 ssthresh，印出進入 avoidence
                    if old_cwnd < self.ssthresh and self.cwnd >= self.ssthresh:
                        print("============== 進入 avoidence============== ")
                else:
                    # Congestion Avoidance: increase cwnd by (MSS * MSS / cwnd) for each ACK
                    # This is approximately 1 MSS per RTT
                    self.cwnd += (packet_size * packet_size) // self.cwnd
                    # print(f"Congestion Avoidance: cwnd = {self.cwnd}, ssthresh = {self.ssthresh}")

        # Remove any other packets that might have been acknowledged by the SACKs
        # (This is a more robust SACK processing, but for this assignment,
        # focusing on the packet_id based ACK is often sufficient given the test setup)
        # For full SACK, you'd iterate self.unacked_packets and remove any whose
        # seq_range falls within any of the provided sacks ranges.
        packets_to_remove = []
        for pid, pkt_info in self.unacked_packets.items():
            pkt_start, pkt_end = pkt_info['seq_range']
            for ack_s, ack_e in sacks:
                if pkt_start >= ack_s and pkt_end <= ack_e:
                    packets_to_remove.append(pid)
                    bytes_freed += (pkt_end - pkt_start)
                    self.last_acked_seq = max(self.last_acked_seq, pkt_end)
                    break # Acknowledged by this SACK, no need to check other SACKs for this packet

        for pid in packets_to_remove:
            self.unacked_packets.pop(pid)
            if pid in self.sent_time:
                del self.sent_time[pid]

        # 簡化版 Fast Recovery
        if self.in_fast_recovery:
            # 檢查是否收到了先前被認定遺失的封包 (case 3)
            if self.recovery_seq is not None and any(ack_start <= self.recovery_seq < ack_end for ack_start, ack_end in sacks):
                # 收到了遺失的封包，離開 Fast Recovery
                self.in_fast_recovery = False
                self.cwnd = self.ssthresh
                print(f"[Fast Recovery Exit] cwnd reset to ssthresh = {self.cwnd}")
            else:
                # 收到非遺失封包的 ACK (case 1 & 2)
                # 增加 cwnd
                if sacks != self.last_sacks:
                    self.cwnd += packet_size
                    # 設定 MAX_CWND
                    MAX_CWND = max(self.cwnd, self.inflight + packet_size)
                    self.cwnd = min(self.cwnd, MAX_CWND)
                    print(f"[Fast Recovery] cwnd = {self.cwnd}, MAX_CWND = {MAX_CWND}")
                # else: 沒有新區段，不加
            self.last_sacks = list(sacks)

        return bytes_freed

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
        # check if all data has been sent and acknowledged
        if self.last_acked_seq >= self.data_len and not self.unacked_packets:
            return None

        # Calculate the start and end sequence for the next packet
        start_seq = self.next_seq_to_send
        end_seq = min(self.data_len, start_seq + payload_size)

        # Check if there are bytes available to send that are not yet acknowledged
        if start_seq >= self.data_len:
             # All data sent. We are waiting for remaining ACKs or timeout.
             return (start_seq, start_seq) # Zero range to indicate no more new data

        seq_range = (start_seq, end_seq)

        # Store packet info for RTT calculation and retransmission
        self.unacked_packets[packet_id] = {
            'seq_range': seq_range,
            'sent_time': time.time()
        }
        self.sent_time[packet_id] = time.time() # This is used by the `start_sender` loop directly.
        self.inflight += (end_seq - start_seq) # 更新 inflight

        self.next_seq_to_send = end_seq
        return seq_range

    def get_cwnd(self) -> int:
        # TODO
        return max(int(self.cwnd), packet_size)

    def get_rto(self) -> float:
        # TODO
        rto = self.estimated_rtt + 4 * self.dev_rtt
        return max(rto, self.min_rto)

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
                    print(
                        f"cwnd: {cwnd}, rto: {rto:.4f}"
                    )
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)

                # Simulate random loss before sending packets
                if random.random() < simloss:
                    print("Dropped!")
                    sender.inflight -= (seq[1] - seq[0]) # 丟包，減少 inflight
                else:
                    # Send the packet
                    sender.sent_time[packet_id] = time.time()
                    client_socket.send(
                        json.dumps(
                            {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                        ).encode())

                inflight += seq[1] - seq[0]
                sender.inflight = inflight # 更新 sender 的 inflight
                packet_id += 1
                print(
                    f"Sending seq: {seq}, id: {packet_id}, cwnd: {cwnd}, rto: {rto:.4f}"
                )

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
                    sender.inflight = inflight # 更新 sender 的 inflight
                    assert inflight >= 0
                    print(
                        f"Got ACK sacks: {received['sacks']}, id: {received['id']}, cwnd: {cwnd}, rto: {rto:.4f}"
                    )
                except socket.timeout:
                    inflight = 0
                    sender.inflight = inflight # 更新 sender 的 inflight
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