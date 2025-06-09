#B124020034
#蔡承家

import argparse
import json
import random
import socket
import os
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
        self.receive_buffer: Dict[int, str] = {}
        self.next_expected_seq = 0

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[Dict[str, Any], str]:
        start_seq, end_seq = seq_range

        #  如果是已經收過的 segment，還是要回 ACK/SACK 給 sender（重傳進來的情況）
        if end_seq <= self.next_expected_seq:
            sack_raw = [(seq, seq + len(payload)) for seq, payload in self.receive_buffer.items()]
            sack_raw.sort()

            sack_merged = []
            for r in sack_raw:
                if not sack_merged:
                    sack_merged.append(r)
                else:
                    last = sack_merged[-1]
                    if r[0] <= last[1]:
                        sack_merged[-1] = (last[0], max(last[1], r[1]))
                    else:
                        sack_merged.append(r)

            print(f"[Receiver DUP] Ignored duplicate {seq_range}, ACK: {self.next_expected_seq}")
            return {
                "ack": self.next_expected_seq,
                "sack": sack_merged
            }, ""

        # 正常處理未收到的 segment
        self.receive_buffer[start_seq] = data

        app_data = ""
        while self.next_expected_seq in self.receive_buffer:
            segment_data = self.receive_buffer.pop(self.next_expected_seq)
            app_data += segment_data
            self.next_expected_seq += len(segment_data)

        ack = self.next_expected_seq

        sack_raw = [(seq, seq + len(payload)) for seq, payload in self.receive_buffer.items()]
        sack_raw.sort()

        sack_merged = []
        for r in sack_raw:
            if not sack_merged:
                sack_merged.append(r)
            else:
                last = sack_merged[-1]
                if r[0] <= last[1]:
                    sack_merged[-1] = (last[0], max(last[1], r[1]))
                else:
                    sack_merged.append(r)

        response = {
            "ack": ack,
            "sack": sack_merged
        }

        print(f"[Receiver] ACK: {ack}, SACKs: {sack_merged}")
        return response, app_data

    def finish(self):
        '''Called when the receiver finishes processing.'''
        print("[Receiver] Finished receiving data.")
        # Add any cleanup logic here if necessary


class Sender:
    def __init__(self, data_len: int):
        self.data_len = data_len
        self.unacked_packets: Dict[int, Dict[str, Any]] = {}
        self.next_seq_to_send = 0
        self.last_acked_seq = 0

        self.sent_time: Dict[int, float] = {}
        self.estimated_rtt: float = 1.0
        self.dev_rtt: float = 0.0
        self.alpha: float = 1/8
        self.beta: float = 1/4
        self.min_rto: float = 0.01

        self.cwnd: int = packet_size
        self.ssthresh: int = 64000
        self.dup_acks: int = 0
        self.last_ack_seq: int = 0
        self.in_fast_recovery: bool = False

        self.missing_seq = None
        self.max_cwnd = None
        self.seen_sack_ranges: Set[Tuple[int, int]] = set()
        self.retransmit_queue: List[Tuple[int, int]] = []
        self.missing_sent = False

        # Initialize highest_sack
        self.highest_sack = 0

    def timeout(self):
        print("Timeout detected!")
        self.ssthresh = max(self.cwnd // 2, packet_size)
        self.cwnd = packet_size
        self.dup_acks = 0
        self.in_fast_recovery = False
        self.next_seq_to_send = self.last_acked_seq
        self.unacked_packets.clear()
        self.sent_time.clear()
        self.retransmit_queue.clear()
        
        # 如果有 missing_seq，加入 retransmit queue
        if self.missing_seq and not self.missing_sent:
            self.retransmit_queue.append(self.missing_seq)
            self.missing_sent = True
            print(f"[Timeout] Retransmit missing_seq {self.missing_seq}")
        
        
        self.seen_sack_ranges.clear()
        self.missing_seq = None
        self.max_cwnd = None
        print(f"[State Change] Timeout -> Slow Start, cwnd: {self.cwnd}, ssthresh: {self.ssthresh}")

    def ack_packet(self, received: Dict[str, Any], packet_id: int) -> int:
        bytes_freed = 0
        if not received:
            return 0

        ack = received["ack"]
        sack_blocks = received.get("sack", [])

        # Merge ACK and SACK blocks
        all_ranges = sack_blocks.copy()
        all_ranges.append((0, ack))
        all_ranges = [tuple(r) for r in all_ranges]
        all_ranges.sort()

        merged = [all_ranges[0]] if all_ranges else []
        for current in all_ranges[1:]:
            last = merged[-1]
            if current[0] <= last[1]:
                merged[-1] = (last[0], max(last[1], current[1]))
            else:
                merged.append(current)

        # === Detect 3 dupACKs ===
        if ack == self.last_ack_seq:
            self.dup_acks += 1
        else:
            self.dup_acks = 1
            self.last_ack_seq = ack

        if self.dup_acks == 3 and not self.in_fast_recovery:
            self.ssthresh = max(self.cwnd // 2, packet_size)
            self.cwnd = self.ssthresh + 3 * packet_size
            self.in_fast_recovery = True
            self.missing_seq = (ack, min(ack + payload_size, self.data_len))
            self.retransmit_queue.append(self.missing_seq)

            # 新增：計算 inflight bytes → 設定 MAX_CWND
            inflight_bytes = sum(pkt['seq_range'][1] - pkt['seq_range'][0] for pkt in self.unacked_packets.values())
            self.max_cwnd = max(self.cwnd, inflight_bytes + packet_size)

            self.seen_sack_ranges.clear()
            
            print(f"[FR DEBUG] merged={merged}, missing_seq={self.missing_seq}") #刪
            
            print(f"[FR ENTRY] 3 dupACKs for {ack}, retransmit {self.missing_seq}, cwnd={self.cwnd}, MAX_CWND={self.max_cwnd}")
        # === Exit Fast Recovery if received new ACK ===
        if self.in_fast_recovery:
            if ack > self.last_ack_seq or (
                self.missing_seq and any(
                    ack_start <= self.missing_seq[0] and ack_end >= self.missing_seq[1]
                    for ack_start, ack_end in merged
                )
            ):
                self.in_fast_recovery = False
                self.cwnd = self.ssthresh
                self.dup_acks = 0
                self.missing_seq = None
                self.missing_sent = False
                self.max_cwnd = None
                self.retransmit_queue.clear()
                self.seen_sack_ranges.clear()
                print(f"[EXIT FR] exited fast recovery due to new ACK. cwnd -> {self.cwnd}")
        # 收到丟失封包的 ACK，退出 Fast Recovery
        if self.in_fast_recovery:
            # Case 3: 收到丟失封包的 ACK，退出 Fast Recovery
            if self.missing_seq and any(
                ack_start <= self.missing_seq[0] and ack_end >= self.missing_seq[1]
                for ack_start, ack_end in merged
            ):
                self.in_fast_recovery = False
                self.cwnd = self.ssthresh
                self.dup_acks = 0
                self.missing_seq = None
                self.missing_sent = False
                self.max_cwnd = None
                self.retransmit_queue.clear()
                self.seen_sack_ranges.clear()
                print(f"[EXIT FR] exited fast recovery due to ACK for missing_seq. cwnd -> {self.cwnd}")
            else:
                # Case 1 和 Case 2: 判斷是否有新區段
                newly_acked_end = max(end for _, end in merged)
                if newly_acked_end > self.highest_sack:
                    self.highest_sack = newly_acked_end
                    self.cwnd = min(self.cwnd + payload_size, self.max_cwnd)
                    print(f"[Fast Recovery] New segment detected, cwnd increased to {self.cwnd}")
                else:
                    print(f"[Fast Recovery] No new segment detected, cwnd remains at {self.cwnd}")


        # === Free packets covered by any merged ACK range ===
        for ack_start, ack_end in merged:
            for pid, pkt_info in list(self.unacked_packets.items()):
                pkt_start, pkt_end = pkt_info['seq_range']
                if pkt_start >= ack_start and pkt_end <= ack_end:
                    self.unacked_packets.pop(pid)
                    if pid in self.sent_time:
                        del self.sent_time[pid]
                    bytes_freed += (pkt_end - pkt_start)
                    self.last_acked_seq = max(self.last_acked_seq, pkt_end)

                    # RTT update
                    sample_rtt = time.time() - pkt_info['sent_time']
                    self.estimated_rtt = (1 - self.alpha) * self.estimated_rtt + self.alpha * sample_rtt
                    self.dev_rtt = (1 - self.beta) * self.dev_rtt + self.beta * abs(sample_rtt - self.estimated_rtt)
                    print(f"[RTT Update] Estimated RTT: {self.estimated_rtt}, Dev RTT: {self.dev_rtt}")

                    # cwnd growth (only when not in FR)
                    if not self.in_fast_recovery:
                        if self.cwnd < self.ssthresh:
                            self.cwnd += packet_size
                            print(f"[Slow Start] cwnd increased to {self.cwnd}")
                        else:
                            self.cwnd += (packet_size * packet_size) // self.cwnd
                            print(f"[Congestion Avoidance] cwnd increased to {self.cwnd}")

        return bytes_freed


    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        # fallback：missing_seq 沒傳就再補一次
        if self.in_fast_recovery and self.missing_seq and not self.missing_sent:
            print(f"[SAFE RETRANS] Re-enqueue missing_seq {self.missing_seq}")
            self.retransmit_queue.append(self.missing_seq)
            self.missing_sent = True


        if self.retransmit_queue:
            seq_range = self.retransmit_queue.pop(0)
            now = time.time()
            self.unacked_packets[packet_id] = {
                'seq_range': seq_range,
                'sent_time': now
            }
            if packet_id not in self.sent_time:
                self.sent_time[packet_id] = now
            print(f"[RETRANS] Retransmitting {seq_range}")
            return seq_range

        if self.last_acked_seq >= self.data_len and not self.unacked_packets:
            return None

        start_seq = self.next_seq_to_send
        end_seq = min(self.data_len, start_seq + payload_size)

        if start_seq >= self.data_len:
            return (start_seq, start_seq)

        seq_range = (start_seq, end_seq)
        self.unacked_packets[packet_id] = {
            'seq_range': seq_range,
            'sent_time': time.time()
        }
        self.sent_time[packet_id] = time.time()

        self.next_seq_to_send = end_seq
        return seq_range

    def get_cwnd(self) -> int:
        # TODO
        return max(int(self.cwnd), packet_size)

    def get_rto(self) -> float:
        # TODO
        rto = self.estimated_rtt + 4 * self.dev_rtt
        rto = max(rto, self.min_rto)
        print(f"[RTO Update] RTO: {rto}")
        return rto

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
    packets between different virtual interfaces.

    '''

    receivers: Dict[str, Receiver] = {}

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket: # Create a UDP socket
        server_socket.bind((ip, port)) # Bind the socket to the given IP and port

        while True:
            data, addr = server_socket.recvfrom(packet_size) # Receive data from the socket
            if addr not in receivers: # If we have not seen this address before, create a new Receiver
                receivers[addr] = Receiver()

            received = json.loads(data.decode()) # 
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
        client_socket.bind(('', 0))
        client_socket.connect((ip, port))
        # When waiting for packets when we call receivefrom, we
        # shouldn't wait more than 500ms

        # Number of bytes that we think are inflight. We are only
        # including payload bytes here, which is different from how
        # TCP does things
        inflight = 0
        packet_id  = 0
        wait = False

        while True:
            # Get the congestion condow
            cwnd = sender.get_cwnd()

            # Do we have enough room in recv_window to send an entire
            # packet?
            if inflight + packet_size <= min(recv_window, cwnd) and not wait:
                seq = sender.send(packet_id)
                if seq is None:
                    # We are done sending
                    client_socket.send('{"type": "fin"}'.encode())
                    break
                elif seq[1] == seq[0]:
                    # No more packets to send until loss happens. Wait
                    wait = True
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)

                # Simulate random loss before sending packets
                if random.random() < simloss:
                    pass
                else:
                    # Send the packet
                    client_socket.send(
                        json.dumps(
                            {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                        ).encode())

                inflight += seq[1] - seq[0]
                packet_id += 1

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
                        continue

                    inflight -= sender.ack_packet(received["sacks"], received["id"])
                    assert inflight >= 0
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