import argparse
import json
import random
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

payload_size = 1200
packet_size = 1500

class Receiver:
    def __init__(self):
        self.buffer = {}
        self.expected_seq = 0

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[List[Tuple[int, int]], str]:
        if seq_range[1] <= self.expected_seq:
            return [(seq_range[0], seq_range[1])], ""

        self.buffer[seq_range[0]] = data
        ack_ranges = [(seq_range[0], seq_range[1])]

        ready_data = ""
        while self.expected_seq in self.buffer:
            packet = self.buffer[self.expected_seq]
            ready_data += packet
            del self.buffer[self.expected_seq]
            newExpected = self.expected_seq + len(packet)
            ack_ranges.append((self.expected_seq, newExpected))
            self.expected_seq = newExpected

        return ack_ranges, ready_data

    def finish(self):
        if self.buffer:
            print("Not all data was sent to the application. There might be an issue.")
        else:
            print("All data was successfully received and delivered.")

class Sender:
    def __init__(self, data_len: int):
        self.data_len = data_len
        self.next_seq = 0
        self.acknowledged = set()
        self.unacknowledged = set()
        self.dup_ack_count = {}
        self.cumulative_sacks = []
        self.last_ack_id_seen = {}
        self.highest_sack = 0
        self.sent_time = {}
        self.inflight = 0
        self.done = False
        self.cwnd = payload_size
        self.ssthresh = 64 * payload_size
        self.phase = "slow_start"
        self.in_fast_recovery = False
        self.max_cwnd = self.cwnd
        self.last_ack_ranges = []
        self.EstimatedRTT = 0.05  
        self.DevRTT = 0.0
        self.alpha = 1 / 8
        self.beta = 1 / 4
        self.seq_to_pid = {}  # 新增

    def timeout(self):
        if self.next_seq >= self.data_len and not self.unacknowledged:
            self.done = True
            return

        if self.unacknowledged:
            self.next_seq = min(self.unacknowledged)
            # --- TCP timeout 行為 ---
            self.ssthresh = max(self.cwnd // 2, payload_size)
            self.cwnd = payload_size
            self.phase = "slow_start"
            self.in_fast_recovery = False
            print("======== Timeout: cwnd reset to slow start ========")

    def ack_packet(self, sacks: List[Tuple[int, int]], packet_id: int) -> int:
        new_acknowledged = 0

        for start, end in sacks:
            for seq in range(start, end, payload_size):
                actual_size = min(payload_size, end - seq)
                if seq in self.unacknowledged:
                    self.unacknowledged.remove(seq)
                    self.acknowledged.add(seq)
                    new_acknowledged += actual_size
                    # RTT計算：用 packet_id
                    if packet_id in self.sent_time:
                        sampleRTT = time.time() - self.sent_time[packet_id]
                        if sampleRTT < 0.001:
                            # 太短的不採用（通常是測試環境內立即收到）
                            sampleRTT = 0.001
                        self.EstimatedRTT = (1 - self.alpha) * self.EstimatedRTT + self.alpha * sampleRTT
                        self.DevRTT = (1 - self.beta) * self.DevRTT + self.beta * abs(sampleRTT - self.EstimatedRTT)
                        del self.sent_time[packet_id]



                self.dup_ack_count.pop(seq, None)
                self.last_ack_id_seen[seq] = packet_id

        if not sacks:
            return new_acknowledged

        base_seq = min(start for start, _ in sacks)
        retransmit_ranges = []

        for seq in list(self.unacknowledged):
            if seq >= base_seq:
                continue

            in_sack = any(start <= seq < end for start, end in sacks)
            if not in_sack:
                if self.last_ack_id_seen.get(seq) != packet_id:
                    self.dup_ack_count[seq] = self.dup_ack_count.get(seq, 0) + 1
                    self.last_ack_id_seen[seq] = packet_id

                    if self.dup_ack_count[seq] == 3 and not self.in_fast_recovery:
                        self.ssthresh = max(self.cwnd // 2, payload_size)
                        self.cwnd = self.ssthresh + 3 * payload_size
                        self.in_fast_recovery = True
                        self.phase = "congestion_avoidance"
                        self.max_cwnd = max(self.cwnd, self.inflight + payload_size)  # 作業要求
                        print(f"======== Enter Fast Recovery: missing {seq} ========")

                    if self.dup_ack_count[seq] % 3 == 0:
                        retransmit_ranges.append((seq, seq + payload_size))
                        self.next_seq = min(self.next_seq, seq)
                        print(f"[RETRANS] retransmit: {seq}–{seq + payload_size}")
            else:
                self.dup_ack_count.pop(seq, None)
                self.last_ack_id_seen[seq] = packet_id

        for start, end in sacks:
            for seq in list(self.dup_ack_count.keys()):
                if start <= seq < end and self.in_fast_recovery:
                    print(f"Exit Fast Recovery: recovered {seq}")
                    self.in_fast_recovery = False
                    self.last_ack_ranges = []

        if sacks:
            self.highest_sack = max(self.highest_sack, max(end for _, end in sacks))

        # --- Add slow start & congestion avoidance logic here ---
        if new_acknowledged > 0:
            if self.phase == "slow_start":
                self.cwnd += new_acknowledged
                if self.cwnd >= self.ssthresh:
                    self.phase = "congestion_avoidance"
                    print("======== Entering CONGESTION AVOIDANCE ========")
            elif self.phase == "congestion_avoidance":
                # 每收到一個 ACK，cwnd 增加 payload_size^2 / cwnd
                self.cwnd += (payload_size * new_acknowledged) / self.cwnd
        # ------------------------------------------------------

        # inflight 修正：最多只能減到 0
        if new_acknowledged > self.inflight:
            self._last_ack_pid = packet_id
            return self.inflight
        self._last_ack_pid = packet_id
        return new_acknowledged

    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        if self.done:
            return None

        if self.next_seq >= self.data_len:
            if self.highest_sack >= self.data_len:
                self.done = True
                return None
            else:
                return (self.data_len, self.data_len)

        while self.next_seq in self.acknowledged:
            self.next_seq = min(self.next_seq + payload_size, self.data_len)
        end_seq = min(self.next_seq + payload_size, self.data_len)
        self.unacknowledged.add(self.next_seq)
        seq_range = (self.next_seq, end_seq)
        self.seq_to_pid[self.next_seq] = packet_id  # 新增
        self.next_seq = end_seq
        return seq_range

    def get_cwnd(self) -> int:
        if self.in_fast_recovery:
            current_acks = sorted(self.acknowledged)
            new_ack_ranges = []

            start = None
            for seq in current_acks:
                if start is None:
                    start = seq
                    end = seq + payload_size
                elif seq == end:
                    end += payload_size
                else:
                    new_ack_ranges.append((start, end))
                    start = seq
                    end = start + payload_size
            if start is not None:
                new_ack_ranges.append((start, end))

            # Fast Recovery 狀態下，檢查是否有新區段
            if self.in_fast_recovery:
                # 計算這次 SACK 的區段
                if self.last_ack_ranges != new_ack_ranges:
                    self.cwnd += payload_size
                    self.cwnd = min(self.cwnd, self.max_cwnd)
                    self.last_ack_ranges = new_ack_ranges

        return max(self.cwnd, payload_size)

    def get_rto(self) -> float:
        if self.EstimatedRTT == 0.05 and self.DevRTT == 0.0:
            return 1.0  # 尚未有有效測量值，先回傳保守初值
        rto = self.EstimatedRTT + 4 * self.DevRTT
        return max(rto, 0.001)  # 不可小於 1ms

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
                        f"cwnd: {cwnd:.2f}"
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
                    f"Sending seq: {seq}, id: {packet_id}, cwnd: {cwnd:.2f}, rto: {rto:.4f}"
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
                        f"Got ACK sacks: {received['sacks'][0]}"
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