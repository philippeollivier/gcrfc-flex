const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
      const MS_PER_DAY = 86400000;
      const MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
      const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
      const RELATIVE_DAYS = { "-1": "yesterday", 0: "today", 1: "tomorrow" };
      const SENTENCE_BLOCKS = /^(P|LI|TD|TH|DT|DD|DIV|SECTION|ARTICLE|BLOCKQUOTE|H[1-6])$/;
      const startOfToday = new Date();
      startOfToday.setHours(0, 0, 0, 0);

      function isoFromDate(date) {
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${date.getFullYear()}-${month}-${day}`;
      }

      function startOfWeek(date) {
        const monday = new Date(date);
        monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
        return monday.getTime();
      }

      function beginsSentence(element) {
        let precedingText = "";
        let node = element;
        while (node) {
          for (let prev = node.previousSibling; prev; prev = prev.previousSibling) {
            precedingText = prev.textContent + precedingText;
          }
          node = node.parentElement;
          if (!node || SENTENCE_BLOCKS.test(node.tagName)) break;
        }
        precedingText = precedingText.trim();
        return precedingText === "" || /[.!?]["')\]]*$/.test(precedingText);
      }

      document.querySelectorAll("time[data-days-from-today]").forEach((element) => {
        const date = new Date(startOfToday);
        date.setDate(date.getDate() + Number(element.dataset.daysFromToday));
        element.setAttribute("datetime", isoFromDate(date));
      });

      document.querySelectorAll("time[datetime]").forEach((element) => {
        const iso = element.getAttribute("datetime");
        if (!DATE_ONLY.test(iso)) return;
        const [year, month, day] = iso.split("-").map(Number);
        const date = new Date(year, month - 1, day);
        const dayDiff = Math.round((date - startOfToday) / MS_PER_DAY);
        let text;
        if (dayDiff in RELATIVE_DAYS) {
          text = RELATIVE_DAYS[dayDiff];
          if (beginsSentence(element)) text = text[0].toUpperCase() + text.slice(1);
        } else if (startOfWeek(date) === startOfWeek(startOfToday)) {
          text = WEEKDAYS[date.getDay()];
        } else {
          text = `${MONTHS[month - 1]} ${day}`;
          if (year !== startOfToday.getFullYear()) text += `, ${year}`;
        }
        element.textContent = text;
        element.classList.add("variable");
        element.dataset.tooltip = iso;
        element.dataset.copy = iso;
      });

      document.addEventListener("click", (event) => {
        const variable = event.target.closest(".variable[data-copy]");
        if (!variable || !navigator.clipboard) return;
        navigator.clipboard.writeText(variable.dataset.copy).then(() => {
          clearTimeout(variable.copyResetTimer);
          variable.dataset.tooltip = "Copied";
          variable.copyResetTimer = setTimeout(() => {
            variable.dataset.tooltip = variable.dataset.copy;
          }, 1200);
        });
      });

      const toc = document.querySelector("#TOC");
      const headings = document.querySelectorAll("article > section > h2, article > section > h3");
      const minimumTocHeadings = 4;
      const tocActivationBuffer = 16;
      const tocIsEnabled = headings.length >= minimumTocHeadings;

      if (!tocIsEnabled) {
        toc.hidden = true;
      } else {
        const tocList = document.createElement("ul");
        let nestedList;

        headings.forEach((heading) => {
          heading.id ||= heading.textContent
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/(^-|-$)/g, "");

          const item = document.createElement("li");
          const link = document.createElement("a");
          link.href = `#${heading.id}`;
          link.textContent = heading.textContent;
          item.append(link);

          if (heading.tagName === "H2") {
            tocList.append(item);
            nestedList = undefined;
          } else {
            nestedList ||= document.createElement("ul");
            if (!nestedList.parentElement) tocList.lastElementChild?.append(nestedList);
            nestedList.append(item);
          }
        });

        toc.append(tocList);
        const tocLinks = tocList.querySelectorAll("a");

        function updateCurrentSection() {
          let currentIndex = 0;
          headings.forEach((heading, index) => {
            if (heading.getBoundingClientRect().top <= tocActivationBuffer) currentIndex = index;
          });
          tocLinks.forEach((link, index) => {
            if (index === currentIndex) link.setAttribute("aria-current", "location");
            else link.removeAttribute("aria-current");
          });
        }

        window.addEventListener("scroll", updateCurrentSection, { passive: true });
        window.addEventListener("resize", updateCurrentSection);
        updateCurrentSection();
      }
