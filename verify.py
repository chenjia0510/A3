with open("test_file.txt", "r") as f1, open("rcvd-127_0_0_1_56947.txt", "r") as f2:
    content1 = f1.read()
    content2 = f2.read()

    if content1 == content2:
        print("✅ 傳輸成功！兩個檔案完全一致。")
    else:
        print("❌ 檔案內容不同，傳輸有錯。")
