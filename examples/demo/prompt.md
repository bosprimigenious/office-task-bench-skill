# 合成演示：两笔采购付款审核

这是工具测试用的小例子，不是真实商业任务，也不用于验证40分钟。
根据inputs中的规则、发票和付款记录，交付output/review.csv及output/memo.md。
CSV按发票逐行列出invoice_id、eligible、paid、remaining，合计写在Markdown说明中。
逐笔列出可付金额、已付金额和剩余应付；说明是否重复付款，并给出剩余应付总额。
保留发票ID和依据文件位置。金额以元为单位，精确到分。
