// Generic read-more/less toggle.
// Any button with [data-read-more-btn] and aria-controls="<id>" toggles
// the collapsed state class on its target.
(function () {
    document.querySelectorAll('[data-read-more-btn]').forEach(function (btn) {
        var targetId = btn.getAttribute('aria-controls');
        var target = document.getElementById(targetId);
        if (!target) return;

        var collapsedClass = 'read-more-target--collapsed';

        btn.addEventListener('click', function () {
            var isCollapsed = target.classList.toggle(collapsedClass);
            btn.textContent = isCollapsed ? 'Read more' : 'Read less';
            btn.setAttribute('aria-expanded', String(!isCollapsed));
        });
    });
}());
