"""Reviewed official references for the original built-in policy guides."""
from app import storage

REFERENCES = {
    'P-001': ('高龄津贴申请指南', '浙江省民政厅等三部门 · 高龄津贴发放通知（省级原文 PDF）', 'https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3176/site/attach/0/b3e27e38a3b44e399482554e47c6a800.pdf'),
    'P-002': ('居住证办理与签注', '国家政务服务平台 · 上城区连续就读居住证办理（分类参考）', 'https://gjzwfw.www.gov.cn/fwmh/item/v3/item_113301020024941552400070911100102.do'),
    'P-003': ('最低生活保障申请咨询', '杭州市民政局 · 申请最低生活保障需要提供哪些材料', 'https://www.hangzhou.gov.cn/art/2024/10/16/art_1229824783_59103763.html'),
    'P-004': ('退役军人优待服务咨询', '退役军人事务部 · 优待证管理办法政策解读（全国参考）', 'https://www.mva.gov.cn/jiedu/zcjd/202112/t20211213_54031.html'),
}


def attach_default_references():
    # Run once per original row; preserve administrator-provided references.
    with storage.transaction(write=True, tables=('policies',)) as (data, db):
        for policy in data['policies']:
            reference = REFERENCES.get(policy['id'])
            if not reference or policy['title'] != reference[0] or policy.get('source_url'):
                continue
            policy['source'], policy['source_url'] = reference[1:]
            if policy['id'] == 'P-001' and policy['summary'] == '具有本社区户籍或符合属地服务要求的高龄老人，可按年龄档申请高龄津贴。具体年龄门槛和金额以杭州市及所在街道最新口径为准。':
                policy['summary'] = '浙江省户籍且年满80周岁的老年人，高龄津贴原则上通过数字化主动发放，无需本人及家庭申请；对漏发等情况有异议的，可向属地社区或民政部门咨询补发。具体待遇以属地现行规定为准。'
                policy['steps'] = ['核对户籍、年龄及具备金融功能的社保卡信息', '留意属地民政部门主动发放情况，一般无需另行申请', '如有漏发或信息异常，联系社区、街道或民政部门核实补发']
            storage.audit(db, '补充默认政策官方参考链接', policy['id'], 'system')
