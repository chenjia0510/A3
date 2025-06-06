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
        # ---------------  唯一改動：初始化收包狀態 ----------------
        self.buf: Dict[int, str] = {}   # key = seq_start
        self.expected = 0               # 下一個應收 seq
    # ----------------------------------------------------------------

    def data_packet(self, seq_range: Tuple[int, int], data: str)\
            -> Tuple[List[Tuple[int, int]], str]:
        # -----------------  最簡累積 ACK + 順序交付  -----------------
        start, end = seq_range

        # 已收過就直接回 ACK；不重複入 buffer
        if end <= self.expected or start in self.buf:
            return ([(0, self.expected)], "")

        self.buf[start] = data

        # 只要緊鄰 expected，就依序交付並前推 expected
        delivered = []
        app_out = ""
        while self.expected in self.buf:
            pkt = self.buf.pop(self.expected)
            app_out += pkt
            self.expected += len(pkt)
        return ([(0, self.expected)], app_out)
    # ----------------------------------------------------------------

    def finish(self):
        # 小作業：簡單一致性檢查
        if self.buf:
            print("Receiver warning: data gap remains!")
        pass

class Sender:
    def __init__(self, data_len: int, fixed_cwnd: int = 120_000):  # <<< changed
        # --------------------  基本狀態 ---------------------------
        self.data_len = data_len
        self.next_seq = 0                 # 將要傳送的 seq
        self.unacked: Dict[int, int] = {} # seq_start → length
        self.cwnd_bytes = 120_000         # 固定 120 kB 視窗
        self.rto = 0.5                    # 常數 RTO
        self.done = False
        self.cwnd_bytes = fixed_cwnd 
        self.send_time: Dict[int, float] = {}
    # ---------------------------------------------------------------

    def timeout(self):
        # ------------  timeout：重傳第一個未 ACK 封包 --------------
        if not self.unacked:
            return
        first = min(self.unacked)
        self.next_seq = first
        self.cwnd_bytes = payload_size    # 慢啟動回 1 MSS
        self.unacked.pop(first, None)     # 讓 send() 重新送
    # ---------------------------------------------------------------

    def ack_packet(self, sacks: List[Tuple[int, int]], packet_id: int) -> int:
        # ----------------  只用累積 ACK 第一段 ---------------------
        if not sacks:
            return 0
        acked_to = sacks[0][1]            # (0, x)
        newly = 0
        for seq in list(self.unacked):
            if seq + self.unacked[seq] <= acked_to:
                newly += self.unacked.pop(seq)
        return newly
    # ---------------------------------------------------------------

    def send(self, packet_id: int) -> Optional[Tuple[int, int]]:
        # -----------------  pipeline 傳送邏輯 ----------------------
        if self.done:
            return None

        # 若資料全 ACK，結束
        if self.next_seq >= self.data_len and not self.unacked:
            self.done = True
            return None

        # 若已全部排完但仍有未 ACK -> 返回空區段讓外層等待
        if self.next_seq >= self.data_len:
            return (self.data_len, self.data_len)

        # 若 seq 已被列入 unacked，直接跳到下一包
        while self.next_seq in self.unacked:
            self.next_seq += payload_size

        # 產生新封包
        end = min(self.next_seq + payload_size, self.data_len)
        self.unacked[self.next_seq] = end - self.next_seq
        rng = (self.next_seq, end)
        self.next_seq = end
        return rng
    # ---------------------------------------------------------------

    def get_cwnd(self) -> int:
        return max(packet_size, self.cwnd_bytes)

    def get_rto(self) -> float:
        return self.rto







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


def start_sender(ip: str, port: int, data: str, recv_window: int, simloss: float, pkts_to_reorder: int, fixed_cwnd: int):
    sender = Sender(len(data), fixed_cwnd=fixed_cwnd)

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
            start_sender(args.ip, args.port, data, args.recv_window, args.simloss,1, args.fixed_cwnd)

if __name__ == "__main__":
    main()