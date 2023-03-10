module.exports = ({url, headers}) => ({
  message: "I am a super proprietary API",
  query: Object.fromEntries(new URL(url, `http://${headers.host}`).searchParams)
})
