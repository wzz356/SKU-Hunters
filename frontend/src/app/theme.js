/* ============================================================
 * SKU Hunters · antd ConfigProvider theme
 * 将 semantic token 映射到 antd 5 的 theme token。
 * 注意：错误语义用 --color-danger（#FF4D4F），与品牌红（#E60012）严格分离。
 * ============================================================ */

export const theme = {
  token: {
    // 主色：粉紫（--color-action-primary）
    colorPrimary: '#7A5FD0',
    colorPrimaryHover: '#6A4FC0',
    colorInfo: '#1677FF',
    colorSuccess: '#52C41A',
    colorWarning: '#FAAD14',
    // 错误语义（非品牌红）
    colorError: '#FF4D4F',
    // 文本
    colorText: '#262626',
    colorTextSecondary: '#595959',
    colorTextTertiary: '#6B6B6B',
    // 边框/分割
    colorBorder: '#F0F0F0',
    colorBorderSecondary: '#F0F0F0',
    // 圆角
    borderRadius: 8,
    // 字号
    fontSize: 13,
    // 字体
    fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif",
  },
  components: {
    Layout: {
      siderBg: '#FFFFFF',
      bodyBg: '#F7F7F8',
      headerBg: '#FFFFFF',
    },
    Menu: {
      itemSelectedBg: '#F6F3FF',
      itemSelectedColor: '#7A5FD0',
      itemBorderRadius: 8,
    },
    Card: {
      borderRadiusLG: 12,
      boxShadowTertiary: '0 1px 2px rgba(0, 0, 0, 0.03), 0 2px 8px rgba(0, 0, 0, 0.06)',
      headerFontSize: 15,
    },
    Steps: {
      iconSize: 28,
      titleLineHeight: 24,
    },
    Tag: {
      borderRadiusSM: 4,
    },
    Progress: {
      defaultColor: '#7A5FD0',
    },
  },
};
