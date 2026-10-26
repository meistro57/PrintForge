---
title: "Appendix A: Unsafe Input"
order: 4
---

<script>alert("x")</script>

Inline <span onclick="evil()">html</span> and a break<br>here.

<!-- an author note -->

[js link](javascript:alert(1)) and [file link](file:///etc/passwd) and [ftp link](ftp://example.com/x) and [phone](tel:+15550100).
