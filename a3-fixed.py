# Your Name: xxxx
# Your ID: Bxxxxxx

import argparse
import json
import random
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

# The maximum size of the data contained within one packet
payload_size = 1200
# The maximum size of a packet including all the JSON formatting
packet_size = 1500


class Receiver:
    def __init__(self):
        # ---------- TODO ①  Receiver 初始化 ----------
        self.buf: Dict[int, str] = {}   # seq_start -> payload
        self.expected = 0               # 下一個應交付序號

    def data_packet(self, seq_range: Tuple[int, int], data: str) -> Tuple[List[Tuple[int, int]], str]:
        # ---------- TODO ②  收到一個 data 封包 ----------
        start, end = seq_range

        # 已收過 => 只回 cumulative ACK
        if end <= self.expected:
            return ([(0, self.expected)], "")

        # 新資料放進 buffer
        if start not in self.buf:
            self.buf[start] = data

        # 交付連續資料
        app_out = ""
        while self.expected in self.buf:
            pkt = self.buf.pop(self.expected)
            app_out += pkt
            self.expected += len(pkt)

        # 回 ACK: 0 ~ expected
        return ([(0, self.expected)], app_out)

    def finish(self):
        if self.buf:
            print("Receiver warning: data gap remains!")


class Sender:
    def __init__(self, data_len: int, fixed_cwnd: Optional[int] = None):
        # ---------- TODO ③  Sender 初始化 ----------
        self.data_len = data_len
        self.next_seq = 0
        self.cwnd = fixed_cwnd or payload_size            # bytes
        self.unacked: Dict[int, int] = {}                 # seq_start -> len
        self.retx_q: List[Tuple[int, int]] = []           # 重傳佇列
        self.sent_time: Dict[int, float] = {}             # seq_start -> t
        self.rto = 0.5
        self.done = False

    def timeout(self):
        # ---------- TODO ④  timeout 行為 ----------
        if not self.unacked:
            return
        first = min(self.unacked)
        self.retx_q.append((first, first + self.unacked[first]))
        self.cwnd = payload_size  # multiplicative decrease

    def ack_packet(self, sacks: List[Tuple[int, int]], packet_id: int) -> int:
        # ---------- TODO ⑤  處理 ACK ----------
        if not sacks:
            return 0
        acked_to = sacks[0][1]  # 只看 cumulative (0, x)
        released = 0
        for seq in list(self.unacked):
            if seq + self.unacked[seq] <= acked_to:
                released += self.unacked.pop(seq)
        return released

    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        # ---------- TODO ⑥  決定要送哪些位元組 ----------
        if self.done:
            return None

        # 1. 先送重傳
        if self.retx_q:
            return self.retx_q.pop(0)

        # 2. 所有資料皆已送完，只等 ACK
        if self.next_seq >= self.data_len:
            if not self.unacked:
                self.done = True
                return None
            return (self.data_len, self.data_len)

        # 3. 跳過已列入 unacked 的序號
        while self.next_seq in self.unacked:
            self.next_seq += payload_size

        end = min(self.next_seq + payload_size, self.data_len)
        self.unacked[self.next_seq] = end - self.next_seq
        rng = (self.next_seq, end)
        self.next_seq = end
        return rng

    def get_cwnd(self) -> int:
        return max(packet_size, int(self.cwnd))

    def get_rto(self) -> float:
        return self.rto


# ==== 以下為 starter 原本內容（未改動，僅插入 sent_time 記錄那 1 行） ====

def start_receiver(ip: str, port: int):
    receivers: Dict[str, Tuple[Receiver, Any]] = {}
    received_data = ''
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server_socket:
        server_socket.bind((ip, port))

        while True:
            print("======= Waiting =======")
            data, addr = server_socket.recvfrom(packet_size)
            if addr not in receivers and json.loads(data.decode())["type"] == "data":
                outfile = open(f'rcvd-{addr[0]}-{addr[1]}.txt', 'w')
                receivers[addr] = (Receiver(), outfile)

            received = json.loads(data.decode())
            if received["type"] == "data":
                assert type(received["seq"]) is list
                assert type(received["seq"][0]) is int and type(received["seq"][1]) is int
                assert type(received["payload"]) is str
                assert len(received["payload"]) <= payload_size

                sacks, app_data = receivers[addr][0].data_packet(tuple(received["seq"]), received["payload"])
                receivers[addr][1].write(app_data)
                receivers[addr][1].flush()
                print(f"Received seq: {received['seq']}, id: {received['id']}, sending sacks: {sacks}")
                received_data += app_data
                server_socket.sendto(json.dumps({"type": "ack", "sacks": sacks, "id": received["id"]}).encode(), addr)
            elif received["type"] == "fin":
                if addr in receivers:
                    receivers[addr][0].finish()
                    if received_data:
                        print("received data (summary): ", received_data[:100], "...", len(received_data))
                        print("received file is saved into: ", receivers[addr][1].name)
                        server_socket.sendto(json.dumps({"type": "fin"}).encode(), addr)
                        received_data = ''
                    receivers[addr][1].close()
                    del receivers[addr]
            else:
                assert False


def start_sender(ip: str, port: int, data: str, recv_window: int, simloss: float,
                 pkts_to_reorder: int, fixed_cwnd: int):
    sender = Sender(len(data), fixed_cwnd=fixed_cwnd)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client_socket:
        buf_size = client_socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        print("Current socket recv buffer size:", buf_size)
        client_socket.connect((ip, port))
        client_socket.settimeout(0.5)

        inflight = 0
        packet_id = 0
        wait = False
        send_buf = []

        while True:
            while inflight + payload_size <= sender.get_cwnd() and not wait:
                seq = sender.send(packet_id)
                got_fin_ack = False
                if seq is None:
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
                    wait = True
                    continue

                assert seq[1] - seq[0] <= payload_size
                assert seq[1] <= len(data)
                print(f"Sending seq: {seq}, id: {packet_id}")

                if random.random() < simloss:
                    print("Dropped!")
                else:
                    # -------- 唯一新增行：記錄傳送時間 --------
                    sender.sent_time[seq[0]] = time.time()
                    # ---------------------------------------
                    pkt_str = json.dumps(
                        {"type": "data", "seq": seq, "id": packet_id, "payload": data[seq[0]:seq[1]]}
                    ).encode()
                    if len(send_buf) < pkts_to_reorder:
                        send_buf += [pkt_str]
                    if len(send_buf) == pkts_to_reorder:
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
                try:
                    print("======= Waiting =======")
                    received = client_socket.recv(packet_size)
                    received = json.loads(received.decode())
                    assert received["type"] == "ack"
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
    parser.add_argument("--fixed_cwnd", type=int, default=30000, help="Fixed congestion window size (in bytes)")

    args = parser.parse_args()

    if args.role == "receiver":
        start_receiver(args.ip, args.port)
    else:
        if args.sendfile is None:
            print("No file to send")
            return
        with open(args.sendfile, 'r') as f:
            data = f.read()
            start_sender(args.ip, args.port, data, args.recv_window, args.simloss, 1, args.fixed_cwnd)


if __name__ == "__main__":
    main()
